from __future__ import annotations

import base64
import json
import plistlib
import subprocess
import time

import requests
from django.core.management.base import BaseCommand, CommandError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp
from apps.signing.models import IOSProvisioningProfile
from apps.signing.services import ensure_ios_signing

APP_ID = 'de.aplusesthetic.app'
FALLBACK_APP_ID = 'de.aplussolution.workforce'
FIREBASE_API = 'https://firebase.googleapis.com/v1beta1'


class Command(BaseCommand):
    help = 'Provision Firebase Android config and Apple Push Notifications capability for A+ Esthetic.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--apple-only', action='store_true')

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(package_name=APP_ID).first() or MobileApp.objects.filter(bundle_id=APP_ID).first()
        if not app:
            raise CommandError(f'Publisher app {APP_ID} not found.')
        apply = bool(options['apply'])
        apple_only = bool(options.get('apple_only'))
        self.stdout.write(f'app={app.slug} apply={str(apply).lower()} apple_only={str(apple_only).lower()}')
        apple = self._apple(app, apply)
        firebase = 'skipped_external_config' if apple_only else self._firebase(app, apply)
        self.stdout.write(f'apple_push_capability={apple}')
        self.stdout.write(f'firebase_android={firebase}')
        self.stdout.write('server_apns_key=external_required')
        config = dict(app.build_config or {})
        self.stdout.write('server_fcm_credentials=publisher_account_available' if config.get('push_firebase_account_id') else 'server_fcm_credentials=missing')

    @staticmethod
    def _profile_push_state(profile):
        try:
            encoded = profile.get_credentials().get('profile_content_base64') or ''
            completed = subprocess.run(
                ['openssl', 'smime', '-inform', 'der', '-verify', '-noverify'],
                input=base64.b64decode(encoded), capture_output=True, check=True,
            ).stdout
            entitlements = (plistlib.loads(completed).get('Entitlements') or {})
            return str(entitlements.get('aps-environment') or 'missing')
        except Exception:
            return 'unknown'

    def _apple(self, app, apply):
        if not app.apple_account or not app.apple_account.configured:
            return 'account_missing'
        client = AppleStoreClient(app.apple_account)
        bundles = client.request('GET', f'/bundleIds?filter[identifier]={APP_ID}&limit=10').get('data', [])
        bundle = next((item for item in bundles if item.get('attributes', {}).get('identifier') == APP_ID), None)
        if not bundle:
            return 'bundle_missing'
        capabilities = client.request('GET', f"/bundleIds/{bundle['id']}/bundleIdCapabilities").get('data', [])
        enabled = any(item.get('attributes', {}).get('capabilityType') == 'PUSH_NOTIFICATIONS' for item in capabilities)
        if not enabled and not apply:
            return 'missing'
        if not enabled:
            body = {
                'data': {
                    'type': 'bundleIdCapabilities',
                    'attributes': {'capabilityType': 'PUSH_NOTIFICATIONS'},
                    'relationships': {'bundleId': {'data': {'type': 'bundleIds', 'id': bundle['id']}}},
                }
            }
            client.request('POST', '/bundleIdCapabilities', data=json.dumps(body))
            enabled = True

        profile = IOSProvisioningProfile.objects.filter(app=app).first()
        state = self._profile_push_state(profile) if profile else 'missing'
        if apply and enabled and state not in {'production', 'development'}:
            if profile:
                try:
                    client.request('DELETE', f'/profiles/{profile.apple_profile_id}')
                except Exception as exc:
                    self.stdout.write(f'apple_old_profile_delete=warning:{exc.__class__.__name__}')
                profile.delete()
            profile = ensure_ios_signing(app)
            state = self._profile_push_state(profile)
        if apply:
            config = dict(app.build_config or {})
            env = dict(config.get('env') or {})
            env['REQUIRE_NATIVE_PUSH'] = '1'
            config['env'] = env
            app.build_config = config
            app.save(update_fields=['build_config', 'updated_at'])
        return f'enabled:profile_{state}' if enabled else 'missing'

    @staticmethod
    def _credentials_for(account):
        if not account or not account.configured:
            return None, None
        info = account.get_credentials()
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )
        credentials.refresh(GoogleAuthRequest())
        return info, credentials

    @staticmethod
    def _error_status(response):
        try:
            error = response.json().get('error', {})
            status = error.get('status') or response.status_code
            message = str(error.get('message') or '').replace('\n', ' ')[:240]
            return f'{status}:{message}' if message else str(status)
        except Exception:
            return str(response.status_code)

    def _request(self, credentials, method, url, **kwargs):
        headers = dict(kwargs.pop('headers', {}))
        headers['Authorization'] = f'Bearer {credentials.token}'
        return requests.request(method, url, headers=headers, timeout=30, **kwargs)

    def _project_number(self, credentials, project_id):
        response = self._request(credentials, 'GET', f'https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}')
        if response.ok:
            return str(response.json().get('projectNumber') or '')
        return ''

    def _enable_service(self, credentials, project_number, service):
        response = self._request(credentials, 'POST', f'https://serviceusage.googleapis.com/v1/projects/{project_number}/services/{service}:enable', json={})
        return response.ok

    def _firebase_candidates(self, app):
        result = []
        seen = set()
        if app.google_account_id:
            result.append(('esthetic', app.google_account))
            seen.add(app.google_account_id)
        fallback = MobileApp.objects.filter(package_name=FALLBACK_APP_ID).select_related('google_account').first()
        if fallback and fallback.google_account_id and fallback.google_account_id not in seen:
            result.append(('aplus_solution', fallback.google_account))
        return result

    def _firebase(self, app, apply):
        last_state = 'account_missing'
        for label, account in self._firebase_candidates(app):
            try:
                info, credentials = self._credentials_for(account)
            except Exception as exc:
                self.stdout.write(f'firebase_candidate_{label}=auth_failed:{exc.__class__.__name__}')
                last_state = 'auth_failed'
                continue
            if not info or credentials is None:
                continue
            project_id = str(info.get('project_id') or account.credential_project_id or '')
            if not project_id:
                last_state = 'project_missing'
                continue

            def list_apps():
                return self._request(credentials, 'GET', f'{FIREBASE_API}/projects/{project_id}/androidApps')

            response = list_apps()
            if not response.ok and apply:
                project_number = self._project_number(credentials, project_id)
                if project_number:
                    self._enable_service(credentials, project_number, 'firebase.googleapis.com')
                    self._enable_service(credentials, project_number, 'fcm.googleapis.com')
                    time.sleep(3)
                    response = list_apps()
            if not response.ok:
                self.stdout.write(f'firebase_candidate_{label}=blocked:{self._error_status(response)}')
                last_state = 'permission_blocked'
                continue

            apps = response.json().get('apps') or []
            android = next((item for item in apps if item.get('packageName') == APP_ID), None)
            if not android and not apply:
                self.stdout.write(f'firebase_candidate_{label}=app_missing')
                last_state = 'app_missing'
                continue
            if not android:
                response = self._request(
                    credentials, 'POST', f'{FIREBASE_API}/projects/{project_id}/androidApps',
                    json={'displayName': 'A+ Esthetic', 'packageName': APP_ID},
                )
                if not response.ok:
                    self.stdout.write(f'firebase_candidate_{label}=create_blocked:{self._error_status(response)}')
                    last_state = 'create_blocked'
                    continue
                android = response.json()

            name = android.get('name') or ''
            if not name:
                last_state = 'app_invalid'
                continue
            config_response = self._request(credentials, 'GET', f'{FIREBASE_API}/{name}/config')
            if not config_response.ok:
                self.stdout.write(f'firebase_candidate_{label}=config_blocked:{self._error_status(config_response)}')
                last_state = 'config_blocked'
                continue
            config_b64 = str(config_response.json().get('configFileContents') or '')
            if not config_b64:
                last_state = 'config_empty'
                continue

            if apply:
                build_config = dict(app.build_config or {})
                env = dict(build_config.get('env') or {})
                env['GOOGLE_SERVICES_JSON_BASE64'] = config_b64
                env['REQUIRE_NATIVE_PUSH'] = '1'
                build_config['env'] = env
                build_config['push_firebase_account_id'] = account.pk
                build_config['push_firebase_source'] = label
                app.build_config = build_config
                app.save(update_fields=['build_config', 'updated_at'])
            self.stdout.write(f'firebase_candidate_{label}=ready')
            return f'ready:{label}'
        return last_state
