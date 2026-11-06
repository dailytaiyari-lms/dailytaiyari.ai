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
    LINKED_DOMAIN_UPDATE_ATTEMPTS = 3
    MANAGED_TAG = 'dailytaiyari-managed'
    TENANT_TAG = 'dailytaiyari-tenant-id'
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

    def _send_request(self, method, url, *, action, headers=None, **kwargs):
        request_headers = self.headers
        if headers:
            request_headers = {**request_headers, **headers}
        try:
            return requests.request(
                method, url, headers=request_headers, timeout=30, **kwargs
            )
        except requests.RequestException as exc:
            raise AzureEmailDomainError(f'Could not {action}: {exc}') from exc

    def _request(self, method, url, *, action, headers=None, **kwargs):
        response = self._send_request(
            method, url, action=action, headers=headers, **kwargs
        )
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
            error = payload.get('error')
            if isinstance(error, dict):
                detail = error.get('message') or payload.get('message')
            else:
                detail = (
                    payload.get('error_description')
                    or payload.get('message')
                    or error
                )
        except ValueError:
            detail = response.text
        detail = (detail or response.reason or 'Unknown Azure error').strip()
        raise AzureEmailDomainError(
            f'Could not {action}: {detail[:1000]}'
        )

    def _assert_domain_ownership(self, domain, tenant_id, resource):
        tags = resource.get('tags') or {}
        is_managed = str(tags.get(self.MANAGED_TAG, '')).lower() == 'true'
        owner_id = str(tags.get(self.TENANT_TAG, '')).lower()
        expected_owner = str(tenant_id).lower()
        if not is_managed:
            raise AzureEmailDomainError(
                f'Email domain {domain} already exists in Azure but is not '
                'managed by DailyTaiyari. A platform administrator must adopt '
                'the resource before this tenant can use it.'
            )
        if owner_id != expected_owner:
            raise AzureEmailDomainError(
                f'Email domain {domain} is already assigned to another tenant.'
            )
        return resource

    def get_domain_if_exists(self, domain):
        action = f'load email domain {domain}'
        response = self._send_request(
            'GET', self._domain_url(domain), action=action
        )
        if response.status_code == 404:
            return None
        self._raise_for_status(response, action)
        return response.json()

    def create_domain(self, domain, tenant_id):
        action = f'create email domain {domain}'
        response = self._send_request(
            'PUT',
            self._domain_url(domain),
            action=action,
            headers={'If-None-Match': '*'},
            json={
                'location': 'Global',
                'tags': {
                    self.MANAGED_TAG: 'true',
                    self.TENANT_TAG: str(tenant_id),
                },
                'properties': {
                    'domainManagement': 'CustomerManaged',
                    'userEngagementTracking': 'Disabled',
                },
            },
        )
        if response.status_code == 412:
            existing = self.get_domain_if_exists(domain)
            if existing is None:
                raise AzureEmailDomainError(
                    f'Could not create email domain {domain}: Azure reported '
                    'a concurrent resource conflict.'
                )
            return self._assert_domain_ownership(
                domain, tenant_id, existing
            )
        self._raise_for_status(response, action)
        return response.json()

    def ensure_domain(self, domain, tenant_id):
        existing = self.get_domain_if_exists(domain)
        if existing is not None:
            return self._assert_domain_ownership(
                domain, tenant_id, existing
            )
        return self.create_domain(domain, tenant_id)

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

    def _update_linked_domain(self, domain_resource_id, *, should_link):
        if not domain_resource_id:
            if should_link:
                raise AzureEmailDomainError(
                    'Azure returned a verified domain without a resource ID.'
                )
            return

        url = self._communication_service_url()
        verb = 'link' if should_link else 'unlink'
        for attempt in range(self.LINKED_DOMAIN_UPDATE_ATTEMPTS):
            load_action = 'load the Azure Communication Service'
            response = self._send_request('GET', url, action=load_action)
            self._raise_for_status(response, load_action)
            resource = response.json()
            etag = response.headers.get('ETag') or resource.get('etag')
            if not etag:
                raise AzureEmailDomainError(
                    'Could not update linked email domains: Azure returned no ETag.'
                )

            properties = resource.get('properties') or {}
            linked = list(properties.get('linkedDomains') or [])
            is_linked = domain_resource_id in linked
            if is_linked == should_link:
                return

            if should_link:
                linked.append(domain_resource_id)
            else:
                linked.remove(domain_resource_id)

            update_action = f'{verb} the email domain'
            update_response = self._send_request(
                'PATCH',
                url,
                action=update_action,
                headers={'If-Match': etag},
                json={'properties': {'linkedDomains': linked}},
            )
            if update_response.status_code == 412:
                if attempt + 1 < self.LINKED_DOMAIN_UPDATE_ATTEMPTS:
                    continue
                raise AzureEmailDomainError(
                    'Could not update linked email domains because the Azure '
                    'Communication Service changed concurrently. Try again.'
                )
            self._raise_for_status(update_response, update_action)

            verified = self._request('GET', url, action=load_action)
            verified_linked = list(
                (verified.get('properties') or {}).get('linkedDomains') or []
            )
            if (domain_resource_id in verified_linked) == should_link:
                return

        raise AzureEmailDomainError(
            f'Could not {verb} the email domain: Azure did not persist the change.'
        )

    def link_domain(self, domain_resource_id):
        self._update_linked_domain(domain_resource_id, should_link=True)

    def unlink_domain(self, domain_resource_id):
        self._update_linked_domain(domain_resource_id, should_link=False)

    def delete_domain(self, domain):
        self._request(
            'DELETE', self._domain_url(domain),
            action=f'delete email domain {domain}',
        )
