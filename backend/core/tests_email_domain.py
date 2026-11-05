from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from core.admin_serializers import TenantEmailDomainSerializer
from core.azure_email_domains import AzureEmailDomainClient
from core.models import Tenant, TenantEmailDomain
from notifications.emails import send_branded_email


def verified_states():
    return {
        key: {'status': 'Verified', 'errorCode': ''}
        for key in ('Domain', 'SPF', 'DKIM', 'DKIM2')
    }


@override_settings(DEFAULT_FROM_EMAIL='platform@example.com')
class TenantEmailDeliveryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Academy')
        self.email_domain = TenantEmailDomain.objects.create(
            tenant=self.tenant,
            domain='academy.example',
            sender_username='notifications',
            sender_name='Academy Mail',
            verification_states=verified_states(),
            sender_provisioned=True,
            is_linked=True,
            is_active=True,
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
    @patch('core.azure_email_domains.requests.request')
    @patch('core.azure_email_domains.requests.post')
    def test_create_domain_uses_arm_api(self, token_post, arm_request):
        token_response = Mock(ok=True, status_code=200)
        token_response.json.return_value = {'access_token': 'token'}
        token_post.return_value = token_response

        arm_response = Mock(ok=True, status_code=200, content=b'{}')
        arm_response.json.return_value = {'id': '/domain/id', 'properties': {}}
        arm_request.return_value = arm_response

        payload = AzureEmailDomainClient().create_domain('academy.example')

        self.assertEqual(payload['id'], '/domain/id')
        request_url = arm_request.call_args.args[1]
        self.assertIn('/domains/academy.example', request_url)
        self.assertIn('/resourceGroups/email-rg/', request_url)
        self.assertEqual(
            arm_request.call_args.kwargs['json']['properties']['domainManagement'],
            'CustomerManaged',
        )
