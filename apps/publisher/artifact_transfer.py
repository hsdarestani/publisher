"""Resumable, bounded agent artifact upload across reverse proxies.

An App Store IPA can exceed Cloudflare's single-request timeout. Native build
agents upload in small independently authenticated chunks, and only finish the
job after the assembled artifact matches the source file's SHA-256.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile

from django.conf import settings
from django.core.files import File
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .agent_completion import _agent_from_request
from .models import Job

CHUNK_SIZE = 2 * 1024 * 1024
MAX_TOTAL_CHUNKS = 4096
MAX_ARTIFACT_BYTES = CHUNK_SIZE * MAX_TOTAL_CHUNKS
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _staging_path(job_id, checksum):
    if not _SHA_RE.fullmatch(str(checksum)):
        raise ValueError("Invalid SHA-256 checksum")
    return Path(settings.MEDIA_ROOT) / "agent-artifact-staging" / str(int(job_id)) / checksum


def _valid_running_build(request, job_pk):
    agent = _agent_from_request(request)
    job = get_object_or_404(Job.objects.select_related("build"), pk=job_pk)
    if (not agent or agent.current_job_id != job.pk
            or job.status != "running"
            or job.type not in {"build_android", "build_ios"}
            or job.build_id is None):
        return None
    return job


@csrf_exempt
@require_POST
def artifact_chunk(request, job_pk):
    """Store one <=2 MiB chunk idempotently; no single upload hits proxy timeout."""
    job = _valid_running_build(request, job_pk)
    if job is None:
        return JsonResponse({"error": "unauthorized"}, status=401)
    try:
        sha = request.headers.get("X-Artifact-Sha256", "").lower()
        idx = int(request.headers.get("X-Artifact-Index", "-1"))
        total = int(request.headers.get("X-Artifact-Total", "0"))
        size = int(request.headers.get("X-Artifact-Size", "0"))
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("Invalid checksum")
        if total <= 0 or total > MAX_TOTAL_CHUNKS or not 0 <= idx < total:
            raise ValueError("Invalid chunk index")
        if not 0 < size <= MAX_ARTIFACT_BYTES:
            raise ValueError("Invalid artifact size")
        if (size + CHUNK_SIZE - 1) // CHUNK_SIZE != total:
            raise ValueError("Incorrect total chunk count")
        expected_length = min(CHUNK_SIZE, size - idx * CHUNK_SIZE)
        if int(request.META.get("CONTENT_LENGTH") or 0) != expected_length:
            raise ValueError("Unexpected chunk length")
        payload = request.body
        if len(payload) != expected_length:
            raise ValueError("Incomplete chunk")
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid chunk"}, status=400)

    folder = _staging_path(job.pk, sha)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{idx:06d}.part"
    if target.exists() and target.stat().st_size == len(payload):
        # Retries are accepted, including after a client-side connection reset.
        if target.read_bytes() == payload:
            Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
            return JsonResponse({"ok": True, "index": idx, "already_received": True})
    fd, temp_path = tempfile.mkstemp(prefix=".chunk-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
    return JsonResponse({"ok": True, "index": idx})


def finalise_staged_artifact(job, metadata):
    """Validate and attach all parts; no native job can succeed with a missing IPA."""
    checksum = str(metadata.get("sha256") or "").lower()
    name = os.path.basename(str(metadata.get("artifact_name") or ""))
    size = int(metadata.get("artifact_size") or 0)
    if not _SHA_RE.fullmatch(checksum) or size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("Invalid staged artifact metadata")
    suffix = ".ipa" if job.type == "build_ios" else ".aab"
    if not name.lower().endswith(suffix) or len(name) > 180:
        raise ValueError("Unexpected artifact extension")
    expected = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
    folder = _staging_path(job.pk, checksum)
    if not folder.is_dir():
        raise ValueError("Artifact upload is missing")
    digest = hashlib.sha256()
    actual_size = 0
    fd, temporary = tempfile.mkstemp(prefix=".assembled-", suffix=suffix, dir=folder)
    try:
        with os.fdopen(fd, "wb") as output:
            for index in range(expected):
                part = folder / f"{index:06d}.part"
                if not part.is_file():
                    raise ValueError(f"Missing artifact chunk {index}")
                with part.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        actual_size += len(block)
                        output.write(block)
        if actual_size != size or digest.hexdigest() != checksum:
            raise ValueError("Artifact SHA-256 or size mismatch")
        with open(temporary, "rb") as source:
            job.build.artifact.save(name, File(source), save=False)
        job.build.artifact_size = size
        job.build.artifact_checksum = checksum
    finally:
        Path(temporary).unlink(missing_ok=True)
        # Do not retain repeated multi-gigabyte uploads after successful save.
        # On failure, keep chunks available for a safe idempotent retry.
    return folder


def cleanup_staged_artifact(folder):
    if not folder:
        return
    for part in folder.glob("*.part"):
        part.unlink(missing_ok=True)
    try:
        folder.rmdir()
        folder.parent.rmdir()
    except OSError:
        pass
