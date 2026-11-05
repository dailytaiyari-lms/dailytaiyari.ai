"""Tenant-admin settings endpoints (branding + feature toggles + payments).

Scoped to the current tenant resolved by ``TenantMiddleware`` from the
``X-Tenant-ID`` header, and restricted to users with the ``admin`` role.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, parsers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.permissions import IsTenantAdmin
from .models import PaymentGateway, TenantEmailDomain, ZoomIntegration
from .admin_serializers import (
    TenantSettingsSerializer, PaymentGatewaySerializer,
    TenantEmailDomainSerializer, ZoomIntegrationSerializer,
)


class TenantSettingsView(generics.RetrieveUpdateAPIView):
    """GET / PATCH the current tenant's branding and feature toggles.

    Accepts multipart (for logo uploads) as well as JSON (for feature toggles).
    """
    serializer_class = TenantSettingsSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]
    parser_classes = [
        parsers.MultiPartParser,
        parsers.FormParser,
        parsers.JSONParser,
    ]

    def get_object(self):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            raise NotFound('No tenant is associated with this request.')
        return tenant


class PaymentGatewayView(generics.GenericAPIView):
    """Manage the current tenant's payment gateways (one per provider).

    A tenant can store credentials for several providers (Razorpay / Cashfree /
    PayU) but exactly one is ``is_active`` at a time — that is the gateway used
    for checkout. Secrets are write-only and never returned.

    * ``GET``    — ``{ gateways: [...], active_provider }`` for all stored providers.
    * ``PUT``    — create/update the gateway for ``provider`` in the body. Setting
      ``is_active`` makes it the sole active gateway (others are deactivated).
    * ``DELETE`` — remove the gateway for ``provider`` (query param or body).
    """
    serializer_class = PaymentGatewaySerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def _tenant(self):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            raise NotFound('No tenant is associated with this request.')
        return tenant

    def _gateways(self):
        return PaymentGateway.objects.filter(tenant=self._tenant())

    def _get_gateway(self, provider):
        if not provider:
            return None
        return self._gateways().filter(provider=provider).first()

    def _list_response(self):
        gateways = self._gateways().order_by('provider')
        data = self.get_serializer(gateways, many=True).data
        active = next((g['provider'] for g in data if g.get('is_active')), None)
        return Response({'gateways': data, 'active_provider': active})

    def get(self, request, *args, **kwargs):
        return self._list_response()

    def put(self, request, *args, **kwargs):
        tenant = self._tenant()
        provider = request.data.get('provider')
        if not provider:
            return Response({'provider': ['This field is required.']}, status=400)
        gateway = self._get_gateway(provider)
        serializer = self.get_serializer(
            gateway, data=request.data, partial=gateway is not None
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = serializer.save(tenant=tenant)
            # Only one gateway may be active per tenant.
            if instance.is_active:
                PaymentGateway.objects.filter(tenant=tenant).exclude(
                    pk=instance.pk
                ).update(is_active=False)
        return self._list_response()

    def delete(self, request, *args, **kwargs):
        provider = request.query_params.get('provider') or request.data.get('provider')
        gateway = self._get_gateway(provider)
        if gateway is not None:
            gateway.delete()
        return self._list_response()


class TenantEmailDomainView(generics.GenericAPIView):
    """Provision, verify, enable and test a tenant-owned Azure email domain."""

    serializer_class = TenantEmailDomainSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def _tenant(self):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            raise NotFound('No tenant is associated with this request.')
        return tenant

    def _domain(self):
        return TenantEmailDomain.objects.filter(tenant=self._tenant()).first()

    def _payload(self, domain=None):
        domain = domain or self._domain()
        return {'email_domain': self.get_serializer(domain).data if domain else None}

    @staticmethod
    def _apply_azure_state(domain, payload):
        properties = payload.get('properties') or {}
        domain.azure_resource_id = payload.get('id') or domain.azure_resource_id
        domain.provisioning_state = properties.get('provisioningState') or ''
        domain.verification_records = properties.get('verificationRecords') or {}
        domain.verification_states = properties.get('verificationStates') or {}
        domain.last_synced_at = timezone.now()
        domain.last_error = ''
        domain.save(update_fields=[
            'azure_resource_id', 'provisioning_state', 'verification_records',
            'verification_states', 'last_synced_at', 'last_error', 'updated_at',
        ])
        return domain

    def _sync(self, domain, client):
        return self._apply_azure_state(
            domain, client.get_domain(domain.domain)
        )

    def _finish_setup_if_verified(self, domain, client):
        if not domain.is_verified:
            return domain
        client.create_sender(
            domain.domain,
            domain.sender_username,
            domain.sender_name or domain.tenant.name,
        )
        client.link_domain(domain.azure_resource_id)
        if not domain.sender_provisioned or not domain.is_linked:
            domain.sender_provisioned = True
            domain.is_linked = True
            domain.save(update_fields=[
                'sender_provisioned', 'is_linked', 'updated_at',
            ])
        return domain

    def get(self, request, *args, **kwargs):
        return Response(self._payload())

    def put(self, request, *args, **kwargs):
        from .azure_email_domains import (
            AzureEmailDomainClient, AzureEmailDomainError,
        )

        domain = self._domain()
        serializer = self.get_serializer(
            domain, data=request.data, partial=domain is not None
        )
        serializer.is_valid(raise_exception=True)
        try:
            client = AzureEmailDomainClient()
            if domain is None:
                azure_state = client.create_domain(
                    serializer.validated_data['domain']
                )
                domain = serializer.save(tenant=self._tenant())
                self._apply_azure_state(domain, azure_state)
            else:
                sender_changed = any(
                    field in serializer.validated_data
                    and serializer.validated_data[field] != getattr(domain, field)
                    for field in ('sender_username', 'sender_name')
                )
                domain = serializer.save()
                if sender_changed:
                    domain.sender_provisioned = False
                    domain.is_active = False
                    domain.save(update_fields=[
                        'sender_provisioned', 'is_active', 'updated_at',
                    ])
                self._sync(domain, client)
                self._finish_setup_if_verified(domain, client)
        except AzureEmailDomainError as exc:
            if domain is not None:
                domain.last_error = str(exc)
                domain.save(update_fields=['last_error', 'updated_at'])
            return Response({'detail': str(exc), **self._payload(domain)}, status=400)
        return Response(self._payload(domain))

    def post(self, request, *args, **kwargs):
        from .azure_email_domains import (
            AzureEmailDomainClient, AzureEmailDomainError,
        )
        from notifications.emails import send_branded_email

        domain = self._domain()
        if domain is None:
            return Response({'detail': 'Configure a sender domain first.'}, status=400)

        action = request.data.get('action', 'verify')
        try:
            client = AzureEmailDomainClient()
            if action == 'refresh':
                self._sync(domain, client)
                self._finish_setup_if_verified(domain, client)
                return Response(self._payload(domain))

            if action == 'verify':
                self._sync(domain, client)
                domain_status = (
                    domain.verification_states.get('Domain') or {}
                ).get('status')
                retryable = {None, 'NotStarted', 'VerificationFailed'}
                if domain_status in retryable:
                    client.initiate_verification(domain.domain, 'Domain')
                elif domain_status == 'Verified':
                    for verification_type in ('SPF', 'DKIM', 'DKIM2'):
                        status = (
                            domain.verification_states.get(verification_type) or {}
                        ).get('status')
                        if status in retryable:
                            client.initiate_verification(
                                domain.domain, verification_type
                            )
                self._sync(domain, client)
                self._finish_setup_if_verified(domain, client)
                return Response({
                    'detail': (
                        'Verification check started. DNS changes can take '
                        '15–30 minutes to appear.'
                    ),
                    **self._payload(domain),
                })

            if action != 'test':
                return Response({'detail': 'Unknown action.'}, status=400)
            if not domain.is_ready:
                return Response(
                    {'detail': 'The domain is not fully verified and linked yet.'},
                    status=400,
                )

            recipient = request.user.email
            sent = send_branded_email(
                self._tenant(),
                recipient,
                subject=f'Test email from {self._tenant().name}',
                heading='Your verified sender domain is working',
                body_html=(
                    '<p>This test was sent from your verified institution domain. '
                    'DailyTaiyari remains the automatic fallback for future '
                    'delivery failures.</p>'
                ),
                force_tenant_domain=True,
                fallback_to_platform=False,
            )
            if not sent:
                return Response(
                    {'detail': 'Azure did not accept the test email.'},
                    status=400,
                )
            return Response({
                'detail': f'Test email sent to {recipient}.',
                **self._payload(domain),
            })
        except AzureEmailDomainError as exc:
            domain.last_error = str(exc)
            domain.save(update_fields=['last_error', 'updated_at'])
            return Response(
                {'detail': str(exc), **self._payload(domain)},
                status=400,
            )

    def delete(self, request, *args, **kwargs):
        from .azure_email_domains import (
            AzureEmailDomainClient, AzureEmailDomainError,
        )

        domain = self._domain()
        if domain is not None:
            try:
                client = AzureEmailDomainClient()
                client.unlink_domain(domain.azure_resource_id)
                client.delete_domain(domain.domain)
            except AzureEmailDomainError as exc:
                domain.last_error = str(exc)
                domain.save(update_fields=['last_error', 'updated_at'])
                return Response(
                    {'detail': str(exc), **self._payload(domain)},
                    status=400,
                )
            domain.delete()
        return Response(self._payload(None))


class ZoomIntegrationView(generics.GenericAPIView):
    """Manage the current tenant's Zoom connection (one per tenant).

    * ``GET``    — the stored connection (secrets replaced by ``has_*`` flags),
      plus the webhook URL to paste into the Zoom app.
    * ``PUT``    — create/update it. Blank secrets keep the stored ones.
    * ``POST``   — "Test connection": fetch a token and the host user from Zoom.
    * ``DELETE`` — disconnect Zoom entirely.
    """
    serializer_class = ZoomIntegrationSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def _tenant(self):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            raise NotFound('No tenant is associated with this request.')
        return tenant

    def _integration(self):
        return ZoomIntegration.objects.filter(tenant=self._tenant()).first()

    def _payload(self, integration=None):
        integration = integration or self._integration()
        if integration is None:
            # Nothing saved yet — still return the webhook URL so the admin can
            # set up the Zoom app before saving credentials.
            return {
                'zoom': None,
                'webhook_url': self.get_serializer().get_webhook_url(None),
            }
        return {
            'zoom': self.get_serializer(integration).data,
            'webhook_url': self.get_serializer(integration).data.get('webhook_url'),
        }

    def get(self, request, *args, **kwargs):
        return Response(self._payload())

    def put(self, request, *args, **kwargs):
        integration = self._integration()
        serializer = self.get_serializer(
            integration, data=request.data, partial=integration is not None
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant=self._tenant())
        # Saving a Secret Token means the admin is wiring up the Zoom app right
        # now, so let the legacy unscoped webhook URL answer Zoom's validation
        # challenge for a short while (the scoped URL never needs this).
        if request.data.get('webhook_secret_token'):
            instance.open_webhook_validation()
        return Response(self._payload(instance))

    def post(self, request, *args, **kwargs):
        """Verify the stored credentials against Zoom and record the result.

        ``{"action": "start_verification"}`` instead opens the short window in
        which the unscoped webhook URL will answer Zoom's URL-validation
        challenge, for admins whose Zoom app predates tenant-scoped URLs.
        """
        from liveclass.zoom import ZoomClient, ZoomError

        integration = self._integration()

        if request.data.get('action') == 'start_verification':
            if integration is None or not integration.webhook_secret_token_encrypted:
                return Response(
                    {'detail': 'Save your Zoom webhook Secret Token first.'}, status=400
                )
            until = integration.open_webhook_validation()
            return Response({
                'detail': 'Webhook verification is open for the next 30 minutes. '
                          'Hit "Validate" in your Zoom app now.',
                'webhook_validation_until': until,
                **self._payload(integration),
            })

        if integration is None or not integration.is_configured:
            return Response(
                {'detail': 'Add your Zoom Account ID, Client ID and Client Secret first.'},
                status=400,
            )
        try:
            user = ZoomClient(integration).verify()
        except ZoomError as exc:
            integration.last_error = str(exc)
            integration.save(update_fields=['last_error', 'updated_at'])
            return Response({'detail': str(exc), **self._payload(integration)}, status=400)

        integration.last_verified_at = timezone.now()
        integration.last_error = ''
        integration.save(update_fields=['last_verified_at', 'last_error', 'updated_at'])
        return Response({
            'detail': 'Zoom connected successfully.',
            'account': {
                'email': user.get('email', ''),
                'display_name': user.get('display_name') or user.get('first_name', ''),
                # 1 = Basic (free), 2 = Licensed/Pro. Reports and registration
                # need a licensed host, so the UI warns when this is Basic.
                'type': user.get('type'),
            },
            **self._payload(integration),
        })

    def delete(self, request, *args, **kwargs):
        integration = self._integration()
        if integration is not None:
            integration.delete()
        return Response(self._payload(None))
