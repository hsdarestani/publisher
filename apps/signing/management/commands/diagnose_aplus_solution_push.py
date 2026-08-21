from __future__ import annotations

import base64
import json
import plistlib
import subprocess

import requests
from django.core.management.base import BaseCommand
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from apps.publisher.models import BuildAgent, MobileApp, Release
from apps.signing.models import IOSProvisioningProfile

APP_ID = 'de.aplussolution.workforce'


class Command(BaseCommand):
    help = 'Report non-secret A+ Solution store/push readiness and probe Firebase access.'

    def add_arguments(self, parser):
        parser.add_argument('--probe-firebase', action='store_true')

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(package_name=APP_ID).first() or MobileApp.objects.filter(bundle_id=APP_ID).first()
        self.stdout.write(f'app_found={"yes" if app else "no"}')
        if not app:
            return

        self.stdout.write(f'app_name={app.name}')
        self.stdout.write(f'app_slug={app.slug}')
        self.stdout.write(f'repository={app.repository_url or "missing"}')
        self.stdout.write(f'framework={app.framework}')
        config = dict(app.build_config or {})
        self.stdout.write(f'build_config_keys={",".join(sorted(config.keys())) or "none"}')
        self.stdout.write(f'build_env_keys={",".join(sorted((config.get("env") or {}).keys())) or "none"}')
        self.stdout.write(f'android_command={config.get("android_command") or "default"}')
        self.stdout.write(f'android_artifact={config.get("android_artifact") or "default"}')
        self.stdout.write(f'ios_command={config.get("ios_command") or "default"}')
        self.stdout.write(f'ios_artifact={config.get("ios_artifact") or "default"}')
        self.stdout.write(f'google_account={"configured" if app.google_account and app.google_account.configured else "missing"}')
        self.stdout.write(f'apple_account={"configured" if app.apple_account and app.apple_account.configured else "missing"}')
        if app.google_account:
            self.stdout.write(f'google_project_id={app.google_account.credential_project_id or "missing"}')
        if app.apple_account:
            self.stdout.write(f'apple_team_id={app.apple_account.apple_team_id or "missing"}')

        latest = Release.objects.filter(app=app).order_by('-build_number', '-created_at').first()
        self.stdout.write(f'latest_release={latest.version_name if latest else "none"}')
        self.stdout.write(f'latest_build_number={latest.build_number if latest else 0}')
        self.stdout.write(f'latest_source_commit={latest.source_commit if latest and latest.source_commit else "missing"}')

        profile = IOSProvisioningProfile.objects.filter(app=app).first()
        self.stdout.write(f'ios_profile={"present" if profile else "missing"}')
        if profile:
            self.stdout.write(f'ios_profile_push={self._profile_push_state(profile)}')

        for platform in ('linux', 'macos'):
            agents = BuildAgent.objects.filter(platform=platform, enabled=True)
            self.stdout.write(f'{platform}_agents={agents.count()} online={sum(1 for agent in agents if agent.online)}')

        if options['probe_firebase']:
            self._probe_firebase(app)

    def _profile_push_state(self, profile):
        try:
            encoded = profile.get_credentials().get('profile_content_base64') or ''
            data = base64.b64decode(encoded)
            completed = subprocess.run(
                ['openssl', 'smime', '-inform', 'der', '-verify', '-noverify'],
                input=data,
                capture_output=True,
                check=True,
            ).stdout
            payload = plistlib.loads(completed)
            entitlements = payload.get('Entitlements') or {}
            value = entitlements.get('aps-environment')
            return str(value or 'missing')
        except Exception as exc:
            return f'unknown:{exc.__class__.__name__}'

    def _probe_firebase(self, app):
        account = app.google_account
        if not account or not account.configured:
            self.stdout.write('firebase_probe=no_google_account')
            return
        credentials_data = account.get_credentials()
        project_id = credentials_data.get('project_id') or ''
        if not project_id:
            self.stdout.write('firebase_probe=no_project_id')
            return
        try:
            credentials = service_account.Credentials.from_service_account_info(
                credentials_data,
                scopes=['https://www.googleapis.com/auth/cloud-platform'],
            )
            credentials.refresh(GoogleAuthRequest())
            response = requests.get(
                f'https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps',
                headers={'Authorization': f'Bearer {credentials.token}'},
                timeout=20,
            )
            self.stdout.write(f'firebase_probe_http={response.status_code}')
            if response.ok:
                apps = response.json().get('apps') or []
                matches = [item for item in apps if item.get('packageName') == APP_ID]
                self.stdout.write(f'firebase_android_app={"present" if matches else "missing"}')
            else:
                try:
                    reason = response.json().get('error', {}).get('status') or 'error'
                except Exception:
                    reason = 'error'
                self.stdout.write(f'firebase_probe_reason={reason}')
        except Exception as exc:
            self.stdout.write(f'firebase_probe=failed:{exc.__class__.__name__}')
