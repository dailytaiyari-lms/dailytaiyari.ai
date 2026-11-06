from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.admin_serializers import (
    TenantEmailDomainSerializer, TenantSettingsSerializer,
)
from core.azure_email_domains import (
    AzureEmailDomainClient, AzureEmailDomainError,
)
from core.models import Tenant, TenantEmailDomain
from core.superadmin_serializers import TenantDetailSerializer
from notifications.emails import send_branded_email
from users.models import User


def verified_states():
    return {
        key: {'status': 'Verified', 'errorCode': ''}
        for key in ('Domain', 'SPF', 'DKIM', 'DKIM2')
    }


@override_settings(DEFAULT_FROM_EMAIL='platform@example.com')
class TenantEmailDeliveryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Academy',
            custom_email_domains_enabled=True,
        )
        self.email_domain = TenantEmailDomain.objects.create(
            tenant=self.tenant,
            domain='academy.example',
            sender_username='notifications',
            sender_name='Academy Mail',
            azure_resource_id='/domains/academy',
            verification_states=verified_states(),
            sender_provisioned=True,
            is_linked=True,
            is_active=True,
        )
        self.admin = User.objects.create_user(
            email='admin@academy.example',
            password='test-password-123',
            tenant=self.tenant,
            role='admin',
        )

    @patch('notifications.emails.EmailMultiAlternatives')
    def test_verified_tenant_domain_is_used_first(self, message_class):
        message_class.return_value.send.return_value = 1

        sent = send_branded_email(
            self.tenant,
            'student@example.com',
            subject='Welcome',
            heading='Welcome',
            body_html='<p>Hello</p>',
        )

        self.assertTrue(sent)
        self.assertEqual(
            message_class.call_args.kwargs['from_email'],
            'Academy Mail <notifications@academy.example>',
        )
        message_class.return_value.send.assert_called_once_with(fail_silently=False)

    @patch('notifications.emails.EmailMultiAlternatives')
    def test_platform_sender_is_used_when_tenant_domain_fails(self, message_class):
        message_class.return_value.send.side_effect = [OSError('Sender rejected'), 1]

        sent = send_branded_email(
            self.tenant,
            'student@example.com',
            subject='Welcome',
            heading='Welcome',
            body_html='<p>Hello</p>',
        )

        self.assertTrue(sent)
        self.assertEqual(message_class.call_count, 2)
        self.assertEqual(
            message_class.call_args_list[0].kwargs['from_email'],
            'Academy Mail <notifications@academy.example>',
        )
        self.assertEqual(
            message_class.call_args_list[1].kwargs['from_email'],
            'Academy <platform@example.com>',
        )
        self.email_domain.refresh_from_db()
        self.assertIn('Sender rejected', self.email_domain.last_error)

    @patch('notifications.emails.EmailMultiAlternatives')
    def test_platform_sender_is_used_when_capability_is_disabled(
        self, message_class
    ):
        self.tenant.custom_email_domains_enabled = False
        self.tenant.save(update_fields=['custom_email_domains_enabled'])
        message_class.return_value.send.return_value = 1

        sent = send_branded_email(
            self.tenant,
            'student@example.com',
            subject='Welcome',
            heading='Welcome',
            body_html='<p>Hello</p>',
        )

        self.assertTrue(sent)
        self.assertEqual(message_class.call_count, 1)
        self.assertEqual(
            message_class.call_args.kwargs['from_email'],
            'Academy <platform@example.com>',
        )

    @patch('core.azure_email_domains.AzureEmailDomainClient')
    def test_email_domain_api_is_blocked_when_capability_is_disabled(
        self, client_class
    ):
        self.tenant.custom_email_domains_enabled = False
        self.tenant.save(update_fields=['custom_email_domains_enabled'])
        client = APIClient()
        token = RefreshToken.for_user(self.admin).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = client.get(
            '/api/v1/tenant-admin/email-domain/',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()['code'],
            'custom_email_domains_disabled',
        )
        client_class.assert_not_called()

    @patch('core.azure_email_domains.AzureEmailDomainClient')
    def test_email_domain_api_rejects_another_tenant_admin(
        self, client_class
    ):
        other_tenant = Tenant.objects.create(
            name='Other Academy',
            custom_email_domains_enabled=True,
        )
        other_admin = User.objects.create_user(
            email='admin@other.example',
            password='test-password-123',
            tenant=other_tenant,
            role='admin',
        )
        client = APIClient()
        token = RefreshToken.for_user(other_admin).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = client.get(
            '/api/v1/tenant-admin/email-domain/',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'tenant_mismatch')
        client_class.assert_not_called()

    def test_tenant_admin_cannot_enable_email_domain_capability(self):
        self.tenant.custom_email_domains_enabled = False
        serializer = TenantSettingsSerializer(
            self.tenant,
            data={'custom_email_domains_enabled': True},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.custom_email_domains_enabled)

    def test_super_admin_serializer_can_enable_email_domain_capability(self):
        self.tenant.custom_email_domains_enabled = False
        serializer = TenantDetailSerializer(
            self.tenant,
            data={'custom_email_domains_enabled': True},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.custom_email_domains_enabled)

    @patch('core.azure_email_domains.AzureEmailDomainClient')
    def test_tenant_remove_unlinks_but_retains_azure_domain(
        self, client_class
    ):
        client = APIClient()
        token = RefreshToken.for_user(self.admin).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = client.delete(
            '/api/v1/tenant-admin/email-domain/',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['email_domain'])
        self.assertFalse(
            TenantEmailDomain.objects.filter(pk=self.email_domain.pk).exists()
        )
        azure_client = client_class.return_value
        azure_client.unlink_domain.assert_called_once_with(
            self.email_domain.azure_resource_id
        )
        azure_client.delete_domain.assert_not_called()

    @patch('core.azure_email_domains.AzureEmailDomainClient')
    def test_tenant_domain_full_lifecycle(self, client_class):
        self.email_domain.delete()
        azure_client = client_class.return_value
        azure_client.ensure_domain.return_value = {
            'id': '/domains/academy-mail',
            'properties': {
                'provisioningState': 'Succeeded',
                'verificationRecords': {
                    'Domain': {
                        'type': 'TXT',
                        'name': 'academy-mail.example',
                        'value': 'ownership-token',
                    },
                },
                'verificationStates': {
                    'Domain': {'status': 'NotStarted'},
                    'SPF': {'status': 'NotStarted'},
                    'DKIM': {'status': 'NotStarted'},
                    'DKIM2': {'status': 'NotStarted'},
                },
            },
        }
        azure_client.get_domain.return_value = {
            'id': '/domains/academy-mail',
            'properties': {
                'provisioningState': 'Succeeded',
                'verificationRecords': {},
                'verificationStates': verified_states(),
            },
        }
        client = APIClient()
        token = RefreshToken.for_user(self.admin).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        headers = {'HTTP_X_TENANT_ID': str(self.tenant.id)}

        create_response = client.put(
            '/api/v1/tenant-admin/email-domain/',
            {
                'domain': 'academy-mail.example',
                'sender_username': 'notifications',
                'sender_name': 'Academy Mail',
            },
            format='json',
            **headers,
        )

        self.assertEqual(create_response.status_code, 200)
        self.assertFalse(create_response.json()['email_domain']['is_ready'])
        azure_client.ensure_domain.assert_called_once_with(
            'academy-mail.example', self.tenant.id
        )

        refresh_response = client.post(
            '/api/v1/tenant-admin/email-domain/',
            {'action': 'refresh'},
            format='json',
            **headers,
        )

        self.assertEqual(refresh_response.status_code, 200)
        self.assertTrue(refresh_response.json()['email_domain']['is_ready'])
        azure_client.create_sender.assert_called_once_with(
            'academy-mail.example', 'notifications', 'Academy Mail'
        )
        azure_client.link_domain.assert_called_once_with(
            '/domains/academy-mail'
        )

        activate_response = client.put(
            '/api/v1/tenant-admin/email-domain/',
            {'is_active': True},
            format='json',
            **headers,
        )

        self.assertEqual(activate_response.status_code, 200)
        self.assertTrue(
            activate_response.json()['email_domain']['is_active']
        )

    @patch('notifications.emails.EmailMultiAlternatives')
    def test_domain_test_does_not_hide_failure_with_fallback(self, message_class):
        message_class.return_value.send.side_effect = OSError('Sender rejected')

        sent = send_branded_email(
            self.tenant,
            'admin@example.com',
            subject='Test',
            heading='Test',
            body_html='<p>Test</p>',
            force_tenant_domain=True,
            fallback_to_platform=False,
        )

        self.assertFalse(sent)
        self.assertEqual(message_class.call_count, 1)

    def test_domain_is_ready_only_after_required_checks_and_linking(self):
        self.assertTrue(self.email_domain.is_verified)
        self.assertTrue(self.email_domain.is_ready)
        self.email_domain.verification_states['DKIM2'] = {'status': 'NotStarted'}
        self.assertFalse(self.email_domain.is_verified)
        self.assertFalse(self.email_domain.is_ready)

    def test_serializer_rejects_invalid_domain(self):
        serializer = TenantEmailDomainSerializer(data={
            'domain': 'https://academy.example/path',
            'sender_username': 'notifications',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('domain', serializer.errors)

    def test_domain_cannot_be_enabled_before_verification(self):
        self.email_domain.verification_states = {}
        self.email_domain.is_linked = False
        self.email_domain.save(
            update_fields=['verification_states', 'is_linked', 'updated_at']
        )
        serializer = TenantEmailDomainSerializer(
            self.email_domain,
            data={'is_active': True},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('is_active', serializer.errors)

    def test_serializer_does_not_expose_azure_resource_details_as_writable(self):
        data = TenantEmailDomainSerializer(self.email_domain).data
        self.assertEqual(data['from_email'], 'notifications@academy.example')
        self.assertTrue(data['is_ready'])


@override_settings(
    AZURE_TENANT_ID='tenant-id',
    AZURE_CLIENT_ID='client-id',
    AZURE_CLIENT_SECRET='client-secret',
    AZURE_SUBSCRIPTION_ID='11112222-3333-4444-5555-666677778888',
    AZURE_EMAIL_RESOURCE_GROUP='email-rg',
    AZURE_EMAIL_SERVICE_NAME='email-service',
    AZURE_COMMUNICATION_RESOURCE_GROUP='communication-rg',
    AZURE_COMMUNICATION_SERVICE_NAME='communication-service',
    AZURE_COMMUNICATION_API_VERSION='2023-03-31',
)
class AzureEmailDomainClientTests(TestCase):
    @staticmethod
    def arm_response(
        payload=None, *, status=200, headers=None, reason='OK'
    ):
        response = Mock(
            ok=200 <= status < 300,
            status_code=status,
            content=b'{}',
            headers=headers or {},
            reason=reason,
            text='',
        )
        response.json.return_value = payload or {}
        return response

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_create_domain_uses_arm_api(self, token_post, arm_request):
        token_response = Mock(ok=True, status_code=200)
        token_response.json.return_value = {'access_token': 'token'}
        token_post.return_value = token_response

        arm_response = Mock(ok=True, status_code=200, content=b'{}')
        arm_response.json.return_value = {'id': '/domain/id', 'properties': {}}
        arm_request.return_value = arm_response

        payload = AzureEmailDomainClient().create_domain(
            'academy.example', 'tenant-123'
        )

        self.assertEqual(payload['id'], '/domain/id')
        request_url = arm_request.call_args.args[1]
        self.assertIn('/domains/academy.example', request_url)
        self.assertIn('/resourceGroups/email-rg/', request_url)
        self.assertEqual(
            arm_request.call_args.kwargs['headers']['If-None-Match'], '*'
        )
        self.assertEqual(
            arm_request.call_args.kwargs['json']['tags'],
            {
                'dailytaiyari-managed': 'true',
                'dailytaiyari-tenant-id': 'tenant-123',
            },
        )
        self.assertEqual(
            arm_request.call_args.kwargs['json']['properties']['domainManagement'],
            'CustomerManaged',
        )

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_existing_domain_requires_dailytaiyari_ownership(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        arm_request.return_value = self.arm_response({
            'id': '/domains/academy',
            'tags': {},
            'properties': {},
        })

        with self.assertRaisesRegex(
            AzureEmailDomainError, 'not managed by DailyTaiyari'
        ):
            AzureEmailDomainClient().ensure_domain(
                'academy.example', 'tenant-123'
            )

        self.assertEqual(arm_request.call_count, 1)

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_existing_domain_cannot_be_claimed_by_another_tenant(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        arm_request.return_value = self.arm_response({
            'id': '/domains/academy',
            'tags': {
                'dailytaiyari-managed': 'true',
                'dailytaiyari-tenant-id': 'tenant-a',
            },
            'properties': {},
        })

        with self.assertRaisesRegex(
            AzureEmailDomainError, 'another tenant'
        ):
            AzureEmailDomainClient().ensure_domain(
                'academy.example', 'tenant-b'
            )

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_original_tenant_can_reattach_managed_domain(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        resource = {
            'id': '/domains/academy',
            'tags': {
                'dailytaiyari-managed': 'true',
                'dailytaiyari-tenant-id': 'tenant-a',
            },
            'properties': {},
        }
        arm_request.return_value = self.arm_response(resource)

        result = AzureEmailDomainClient().ensure_domain(
            'academy.example', 'tenant-a'
        )

        self.assertEqual(result, resource)
        self.assertEqual(arm_request.call_count, 1)

    @patch('core.azure_email_domains.requests.post')
    def test_authentication_failure_returns_azure_message(self, token_post):
        token_post.return_value = self.arm_response(
            {
                'error': 'invalid_client',
                'error_description': 'The client secret is invalid.',
            },
            status=401,
            reason='Unauthorized',
        )

        with self.assertRaisesRegex(
            AzureEmailDomainError, 'client secret is invalid'
        ):
            AzureEmailDomainClient().get_domain('academy.example')

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_arm_throttling_returns_clear_error(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        arm_request.return_value = self.arm_response(
            {'error': {'message': 'Too many requests. Retry later.'}},
            status=429,
            reason='Too Many Requests',
        )

        with self.assertRaisesRegex(
            AzureEmailDomainError, 'Too many requests'
        ):
            AzureEmailDomainClient().get_domain('academy.example')

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_arm_timeout_returns_clear_error(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        arm_request.side_effect = requests.Timeout('request timed out')

        with self.assertRaisesRegex(
            AzureEmailDomainError, 'request timed out'
        ):
            AzureEmailDomainClient().get_domain('academy.example')

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_link_domain_preserves_existing_domains_and_uses_etag(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        existing = '/domains/existing'
        added = '/domains/academy'
        arm_request.side_effect = [
            self.arm_response(
                {'properties': {'linkedDomains': [existing]}},
                headers={'ETag': '"version-1"'},
            ),
            self.arm_response(
                {'properties': {'linkedDomains': [existing, added]}}
            ),
            self.arm_response(
                {'properties': {'linkedDomains': [existing, added]}},
                headers={'ETag': '"version-2"'},
            ),
        ]

        AzureEmailDomainClient().link_domain(added)

        patch_call = arm_request.call_args_list[1]
        self.assertEqual(patch_call.args[0], 'PATCH')
        self.assertEqual(patch_call.kwargs['headers']['If-Match'], '"version-1"')
        self.assertEqual(
            patch_call.kwargs['json']['properties']['linkedDomains'],
            [existing, added],
        )

    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_link_domain_retries_after_concurrent_update(
        self, token_post, arm_request
    ):
        token_post.return_value = self.arm_response(
            {'access_token': 'token'}
        )
        existing = '/domains/existing'
        concurrent = '/domains/concurrent'
        added = '/domains/academy'
        conflict = self.arm_response(
            {'error': {'message': 'ETag mismatch'}},
            status=412,
            reason='Precondition Failed',
        )
        arm_request.side_effect = [
            self.arm_response(
                {'properties': {'linkedDomains': [existing]}},
                headers={'ETag': '"version-1"'},
            ),
            conflict,
            self.arm_response(
                {'properties': {'linkedDomains': [existing, concurrent]}},
                headers={'ETag': '"version-2"'},
            ),
            self.arm_response(
                {
                    'properties': {
                        'linkedDomains': [existing, concurrent, added],
                    }
                }
            ),
            self.arm_response(
                {
                    'properties': {
                        'linkedDomains': [existing, concurrent, added],
                    }
                },
                headers={'ETag': '"version-3"'},
            ),
        ]

        AzureEmailDomainClient().link_domain(added)

        retry_patch = arm_request.call_args_list[3]
        self.assertEqual(
            retry_patch.kwargs['headers']['If-Match'], '"version-2"'
        )
        self.assertEqual(
            retry_patch.kwargs['json']['properties']['linkedDomains'],
            [existing, concurrent, added],
        )
