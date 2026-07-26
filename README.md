# A+ Publisher

A self-hosted release operations platform for A+ Solution GmbH. It connects directly to the official Google Play and Apple App Store APIs, manages builds on your own Linux/macOS agents, submits releases for review, and unifies store analytics, quality issues, commits, stack detection and audit history.

Production URL: `https://publisher.smarbiz.sbs`

## What is included

- Application portfolio with Android/iOS identifiers, source repository and encrypted secrets
- Localized store metadata, icons, screenshots and review credentials
- Release records, readiness checks, staged Google rollouts and Apple release settings
- Self-hosted Linux and macOS build agents with live logs and artifact upload
- Direct Google Play Publishing API workflow: edit, AAB upload, listing/assets, track, validate and commit
- Direct Apple App Store Connect workflow: version, localization, build attachment, review details and review submission
- Apple IPA upload through Apple's official `iTMSTransporter` on your Mac agent
- Google installs, uninstalls, active installs, upgrades, crashes and ANRs from the official Play report bucket
- Google Play Developer Reporting API issue ingestion
- Apple Analytics Reports ingestion for downloads, sessions, crashes, impressions and product-page views
- GitHub commit sync and technology-stack detection
- Technical issue center, dashboards, job retries and audit history
- Docker Compose production deployment with PostgreSQL, Redis, Celery and automatic HTTPS through Caddy

No publishing intermediary such as Fastlane, Codemagic or a third-party release SaaS is required.

## Important platform limits

Apple and Google still require a few one-time console actions. The first app record and legal/account agreements must be completed in the store consoles. iOS signing and IPA creation require macOS/Xcode. Publisher automates the repeatable workflow after that bootstrap.

## Production deployment

The repository workflow deploys every successful push to `main` using these repository secrets:

Required:

- `HOST`: production server IP or hostname
- `PASS`: root SSH password

Optional:

- `SSH_PORT`: defaults to `22`
- `ADMIN_EMAIL`: first administrator email
- `ADMIN_PASSWORD`: first administrator password
- `SENTRY_DSN`: error monitoring; the product works without it

On first deployment the server generates and persists its own Django secret, Fernet encryption key and PostgreSQL password in `/opt/aplus-publisher/.env`. Missing optional secrets do not stop deployment. When no admin password is supplied, a random initial password appears once in the deployment log.

The domain `publisher.smarbiz.sbs` must have an A/AAAA record pointing to `HOST`. Caddy obtains and renews HTTPS automatically.

## Store credentials

Credentials are entered in **Store accounts** inside Publisher, not committed to GitHub.

### Google Play

Create a service account and grant it access to the relevant apps in Play Console. Enable:

- Google Play Android Developer API
- Google Play Developer Reporting API

Paste the complete service-account JSON. For download/install reports, also enter the reporting bucket ID from Play Console, typically `pubsite_prod_rev_…` without or with the `gs://` prefix.

The app remains fully usable when these values are absent; Google actions are simply disabled.

### Apple App Store

Create an App Store Connect API key and enter:

- Issuer ID
- Key ID
- `AuthKey_XXXX.p8` contents
- Team ID and vendor number when relevant

Apple metadata and review submission use the App Store Connect REST API directly. IPA upload uses Apple's Transporter on a registered macOS agent.

## Build agents

Register an agent in **Build agents** and save the token shown once.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r agents/requirements.txt
PUBLISHER_URL=https://publisher.smarbiz.sbs \
PUBLISHER_AGENT_TOKEN=YOUR_TOKEN \
python agents/runner.py
```

For persistent Linux operation, adapt `agents/aplus-publisher-agent.service`.

### Android agent requirements

Install Git and one of:

- Flutter + Android SDK
- Android SDK/JDK/Gradle for native or React Native builds

### macOS agent requirements

Install Git, Xcode command-line tools, accept the Xcode license, and install Flutter when the app uses it. Apple Transporter is invoked through `xcrun iTMSTransporter`.

### Custom build configuration

Each application has an optional `build_config` JSON field. Example:

```json
{
  "android_command": "flutter pub get && flutter build appbundle --release --flavor production",
  "android_artifact": "build/app/outputs/bundle/productionRelease/*.aab",
  "ios_command": "flutter pub get && flutter build ipa --release --flavor production",
  "ios_artifact": "build/ios/ipa/*.ipa",
  "env": {"APP_ENV": "production"}
}
```

Without overrides, Publisher uses sensible Flutter defaults and Gradle `bundleRelease` for Android. Native/React Native iOS projects should specify their Xcode archive/export command and artifact glob.

## Local development

```bash
cp .env.example .env
# Set DEBUG=1 for local use
docker compose up --build
```

Or with local Python:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DEBUG=1 python manage.py migrate
DEBUG=1 python manage.py createsuperuser
DEBUG=1 python manage.py runserver
```

Run validation:

```bash
python manage.py check
python manage.py test
python -m py_compile agents/runner.py
```

## Security model

- Store and repository credentials are encrypted before database storage.
- Agent tokens are shown once and only their SHA-256 hash is stored.
- Store credentials are provided to an agent only for the job that needs them, over HTTPS.
- Apple private keys are written to the Transporter key directory temporarily and deleted after upload.
- Review submission and Google edit commits are audited.
- The default production stack enforces HTTPS and security headers.

For stronger enterprise isolation, set a dedicated `ENCRYPTION_KEY`, use SSH keys instead of the password-based initial deployment, and place the server behind a VPN or SSO proxy.
