"""Azure Communication Services verified-domain management."""
from functools import cached_property
from urllib.parse import quote

import requests
from django.conf import settings


class AzureEmailDomainError(RuntimeError):
    pass


class AzureEmailDomainClient:
    """Small ARM client for tenant email-domain provisioning."""

    MANAGEMENT_URL = 'https://management.azure.com'
    TOKEN_SCOPE = 'https://management.azure.com/.default'
    REQUIRED_SETTINGS = (
        'AZURE_TENANT_ID',
        'AZURE_CLIENT_ID',
        'AZURE_CLIENT_SECRET',
        'AZURE_SUBSCRIPTION_ID',
        'AZURE_EMAIL_RESOURCE_GROUP',
        'AZURE_EMAIL_SERVICE_NAME',
        'AZURE_COMMUNICATION_RESOURCE_GROUP',
        'AZURE_COMMUNICATION_SERVICE_NAME',
    )

    def __init__(self):
        missing = [
            name for name in self.REQUIRED_SETTINGS
            if not getattr(settings, name, '')
        ]
        if missing:
            raise AzureEmailDomainError(
                'Azure verified-domain management is not configured. Missing: '
                + ', '.join(missing)
            )
        self.subscription_id = settings.AZURE_SUBSCRIPTION_ID
        self.resource_group = settings.AZURE_EMAIL_RESOURCE_GROUP
        self.communication_resource_group = (
            settings.AZURE_COMMUNICATION_RESOURCE_GROUP
        )
        self.email_service = settings.AZURE_EMAIL_SERVICE_NAME
        self.communication_service = settings.AZURE_COMMUNICATION_SERVICE_NAME
        self.api_version = getattr(
            settings, 'AZURE_COMMUNICATION_API_VERSION', '2023-03-31'
        )

    @cached_property
    def access_token(self):
        try:
            response = requests.post(
                f'https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}'
                '/oauth2/v2.0/token',
                data={
                    'client_id': settings.AZURE_CLIENT_ID,
                    'client_secret': settings.AZURE_CLIENT_SECRET,
                    'scope': self.TOKEN_SCOPE,
                    'grant_type': 'client_credentials',
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise AzureEmailDomainError(
                f'Could not authenticate with Azure: {exc}'
            ) from exc
        self._raise_for_status(response, 'authenticate with Azure')
        token = response.json().get('access_token')
        if not token:
            raise AzureEmailDomainError('Azure authentication returned no access token.')
        return token

    @property
    def headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def _domain_url(self, domain, suffix=''):
        domain_name = quote(domain, safe='.-')
        return (
            f'{self.MANAGEMENT_URL}/subscriptions/{self.subscription_id}'
            f'/resourceGroups/{quote(self.resource_group, safe="")}'
            '/providers/Microsoft.Communication/emailServices/'
            f'{quote(self.email_service, safe="")}/domains/{domain_name}{suffix}'
            f'?api-version={self.api_version}'
        )

    def _communication_service_url(self):
        return (
            f'{self.MANAGEMENT_URL}/subscriptions/{self.subscription_id}'
            f'/resourceGroups/{quote(self.communication_resource_group, safe="")}'
            '/providers/Microsoft.Communication/CommunicationServices/'
            f'{quote(self.communication_service, safe="")}'
            f'?api-version={self.api_version}'
        )

    def _request(self, method, url, *, action, **kwargs):
        try:
            response = requests.request(
                method, url, headers=self.headers, timeout=30, **kwargs
            )
        except requests.RequestException as exc:
            raise AzureEmailDomainError(f'Could not {action}: {exc}') from exc
        self._raise_for_status(response, action)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _raise_for_status(response, action):
        if response.ok:
            return
        try:
            payload = response.json()
            error = payload.get('error') or {}
            detail = error.get('message') or payload.get('message')
        except ValueError:
            detail = response.text
        detail = (detail or response.reason or 'Unknown Azure error').strip()
        raise AzureEmailDomainError(
            f'Could not {action}: {detail[:1000]}'
        )

    def create_domain(self, domain):
        return self._request(
            'PUT',
            self._domain_url(domain),
            action=f'create email domain {domain}',
            json={
                'location': 'Global',
                'properties': {
                    'domainManagement': 'CustomerManaged',
                    'userEngagementTracking': 'Disabled',
                },
            },
        )

    def get_domain(self, domain):
        return self._request(
            'GET', self._domain_url(domain),
            action=f'load email domain {domain}',
        )

    def initiate_verification(self, domain, verification_type):
        self._request(
            'POST',
            self._domain_url(domain, '/initiateVerification'),
            action=f'start {verification_type} verification for {domain}',
            json={'verificationType': verification_type},
        )

    def create_sender(self, domain, username, display_name):
        username_path = quote(username, safe='.-_')
        return self._request(
            'PUT',
            self._domain_url(domain, f'/senderUsernames/{username_path}'),
            action=f'create sender {username}@{domain}',
            json={
                'properties': {
                    'username': username,
                    'displayName': display_name,
                }
            },
        )

    def link_domain(self, domain_resource_id):
        if not domain_resource_id:
            raise AzureEmailDomainError(
                'Azure returned a verified domain without a resource ID.'
            )
        url = self._communication_service_url()
        resource = self._request(
            'GET', url, action='load the Azure Communication Service'
        )
        properties = resource.get('properties') or {}
        linked = list(properties.get('linkedDomains') or [])
        if domain_resource_id not in linked:
            linked.append(domain_resource_id)
            self._request(
                'PATCH',
                url,
                action='link the verified email domain',
                json={'properties': {'linkedDomains': linked}},
            )

    def unlink_domain(self, domain_resource_id):
        if not domain_resource_id:
            return
        url = self._communication_service_url()
        resource = self._request(
            'GET', url, action='load the Azure Communication Service'
        )
        properties = resource.get('properties') or {}
        linked = list(properties.get('linkedDomains') or [])
        if domain_resource_id in linked:
            linked.remove(domain_resource_id)
            self._request(
                'PATCH',
                url,
                action='unlink the email domain',
                json={'properties': {'linkedDomains': linked}},
            )

    def delete_domain(self, domain):
        self._request(
            'DELETE', self._domain_url(domain),
            action=f'delete email domain {domain}',
        )
