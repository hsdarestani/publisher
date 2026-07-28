from django.shortcuts import get_object_or_404, render

from apps.publisher.models import MobileApp

from .services import get_or_create_profile


def public_account_deletion(request, slug):
    app = get_object_or_404(MobileApp, slug=slug)
    profile = get_or_create_profile(app)
    support_email = profile.support_email or "support@aplus-solution.de"
    return render(
        request,
        "compliance/account_deletion.html",
        {
            "app": app,
            "profile": profile,
            "support_email": support_email,
        },
    )
