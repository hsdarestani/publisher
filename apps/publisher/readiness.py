from urllib.parse import urlparse

class Check:
    def __init__(self, key, label, status, message, platform="shared"):
        self.key, self.label, self.status, self.message, self.platform = key, label, status, message, platform
    def as_dict(self):
        return self.__dict__


def _url_ok(value):
    try:
        return urlparse(value).scheme in {"http", "https"} and bool(urlparse(value).netloc)
    except Exception:
        return False


def evaluate_release(release):
    app = release.app
    checks = []
    def add(key, label, ok, ok_msg, fail_msg, platform="shared", severity="error"):
        checks.append(Check(key, label, "pass" if ok else severity, ok_msg if ok else fail_msg, platform))

    add("privacy", "Privacy policy", _url_ok(app.privacy_policy_url), "Privacy policy URL is present.", "Add a valid privacy policy URL.")
    add("support", "Support URL", _url_ok(app.support_url), "Support URL is present.", "Add a valid support URL.", severity="warning")
    add("localization", "Store localization", app.localizations.exists(), "At least one localization exists.", "Create at least one store localization.")
    for loc in app.localizations.all():
        add(f"title-{loc.pk}", f"{loc.locale} title", bool(loc.title), "Title is ready.", "Title is missing.")
        add(f"description-{loc.pk}", f"{loc.locale} description", bool(loc.full_description), "Description is ready.", "Full description is missing.")
        if len(loc.title) > 30:
            checks.append(Check(f"title-length-{loc.pk}", f"{loc.locale} title length", "warning", "Apple commonly limits app names to 30 characters; verify this locale."))
    add("version", "Version", bool(release.version_name and release.build_number), "Version and build number are ready.", "Version or build number is missing.")
    add("source", "Source repository", bool(app.repository_url), "Repository is linked.", "Link a repository before automated builds.", severity="warning")
    if app.requires_login:
        add("review-login", "Reviewer login", bool(app.review_username and app.get_review_password()), "Reviewer credentials are stored.", "Reviewer credentials are required because the app needs login.")
    if app.supports_android:
        add("android-id", "Android package", bool(app.package_name), "Package name is set.", "Android package name is missing.", "android")
        add("google-account", "Google account", bool(app.google_account and app.google_account.configured), "Google Play credentials are configured.", "Google Play is not configured; Android publishing stays disabled.", "android", "warning")
        add("android-icon", "Android icon", app.assets.filter(kind="icon", platform__in=["android", "shared"]).exists(), "Android icon exists.", "Upload an Android/shared app icon.", "android")
        add("android-screens", "Android screenshots", app.assets.filter(kind="screenshot", platform="android").exists(), "Android screenshots exist.", "Upload Android screenshots.", "android", "warning")
    if app.supports_ios:
        add("ios-id", "iOS bundle ID", bool(app.bundle_id), "Bundle ID is set.", "iOS bundle ID is missing.", "ios")
        add("apple-account", "Apple account", bool(app.apple_account and app.apple_account.configured), "App Store credentials are configured.", "App Store is not configured; iOS publishing stays disabled.", "ios", "warning")
        add("ios-icon", "iOS icon", app.assets.filter(kind="icon", platform__in=["ios", "shared"]).exists(), "iOS icon exists.", "Upload an iOS/shared app icon.", "ios")
        add("ios-screens", "iOS screenshots", app.assets.filter(kind="screenshot", platform="ios").exists(), "iOS screenshots exist.", "Upload iOS screenshots.", "ios", "warning")
    build_states = {b.platform: b.status for b in release.builds.all()}
    if app.supports_android:
        add("android-build", "Android build", build_states.get("android") == "succeeded", "A successful Android build is available.", "A successful Android build is not available.", "android")
    if app.supports_ios:
        add("ios-build", "iOS build", build_states.get("ios") == "succeeded", "A successful iOS build is available.", "A successful iOS build is not available.", "ios")
    data = [c.as_dict() for c in checks]
    return {"checks": data, "errors": sum(c["status"] == "error" for c in data), "warnings": sum(c["status"] == "warning" for c in data), "passed": sum(c["status"] == "pass" for c in data), "ready": not any(c["status"] == "error" for c in data)}
