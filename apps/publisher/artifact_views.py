from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import Job


@login_required
def job_artifact_download(request, pk):
    job = get_object_or_404(Job.objects.select_related("build"), pk=pk)
    build = job.build
    if not build or not build.artifact:
        raise Http404("Build artifact not found.")

    original_name = Path(build.artifact.name).name
    if build.platform == "android":
        filename = original_name[:-4] + ".aab" if original_name.lower().endswith(".zip") else original_name
        if not filename.lower().endswith(".aab"):
            filename = "app-release.aab"
    elif build.platform == "ios":
        filename = original_name if original_name.lower().endswith(".ipa") else "app-release.ipa"
    else:
        filename = original_name or "build-artifact.bin"

    response = FileResponse(
        build.artifact.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
