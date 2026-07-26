from __future__ import annotations

import base64
import io
import zipfile

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.publisher.cloud_auth import github_cloud_agent
from apps.publisher.models import Job, MobileApp

from .services import ensure_android_signing


@csrf_exempt
@require_GET
def job_credentials(request, job_pk):
    agent = github_cloud_agent(request)
    if not agent or agent.platform != "linux" or agent.current_job_id != job_pk:
        return JsonResponse({"error": "unauthorized"}, status=401)

    job = get_object_or_404(Job.objects.select_related("app"), pk=job_pk)
    if job.type != "build_android" or not job.app_id:
        return JsonResponse({"error": "android_build_job_required"}, status=400)

    credential = ensure_android_signing(job.app)
    return JsonResponse(
        {
            "android_signing": credential.get_credentials(),
            "certificate_sha256": credential.certificate_sha256,
        }
    )


@login_required
@require_GET
def download_backup(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    credential = ensure_android_signing(app)
    values = credential.get_credentials()
    keystore = base64.b64decode(values["keystore_base64"])

    key_properties = "\n".join(
        [
            f"storePassword={values['store_password']}",
            f"keyPassword={values['key_password']}",
            f"keyAlias={values['key_alias']}",
            "storeFile=../upload-keystore.jks",
            "",
        ]
    )
    readme = (
        "A+ Publisher Android upload-key backup\n\n"
        f"Application: {app.name}\n"
        f"Package: {app.package_name}\n"
        f"Certificate SHA-256: {credential.certificate_sha256}\n\n"
        "Keep this archive private. Google Play uses this upload key to verify future AAB uploads.\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("upload-keystore.jks", keystore)
        archive.writestr("key.properties", key_properties)
        archive.writestr("README.txt", readme)
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{app.slug}-android-upload-key.zip"'
    response["Cache-Control"] = "no-store"
    return response
