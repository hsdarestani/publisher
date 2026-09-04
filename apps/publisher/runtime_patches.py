"""Narrow production safeguards for store-release operations.

A+ Esthetic already has approved Google Play listing media. Release publishing
must not rewrite those images: one historical Publisher asset is rejected by the
Play media endpoint as ``Image type invalid`` even though the AAB itself is
valid. Store-content edits remain available through the dedicated content-sync
path; normal release publication only needs the existing listing plus the new
bundle/track.
"""


def install():
    from apps.integrations.google_play import GooglePlayClient

    if getattr(GooglePlayClient.publish_release, "_aplus_esthetic_media_guard", False):
        return

    original = GooglePlayClient.publish_release

    def guarded_publish_release(self, app, release, build_obj, localizations, assets, submit=True):
        if getattr(app, "slug", "") == "a-esthetic":
            assets = []
        return original(self, app, release, build_obj, localizations, assets, submit=submit)

    guarded_publish_release._aplus_esthetic_media_guard = True
    guarded_publish_release.__name__ = original.__name__
    guarded_publish_release.__doc__ = original.__doc__
    GooglePlayClient.publish_release = guarded_publish_release
