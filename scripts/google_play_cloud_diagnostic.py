from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import service_account


SCOPE = "https://www.googleapis.com/auth/androidpublisher"
ENDPOINTS = (
    ("androidpublisher.googleapis.com", "https://androidpublisher.googleapis.com/androidpublisher/v3"),
    ("www.googleapis.com legacy", "https://www.googleapis.com/androidpublisher/v3"),
)


def compact_response(name: str, response: requests.Response) -> dict:
    content_type = response.headers.get("content-type", "").split(";")[0]
    try:
        body = response.json()
    except Exception:
        body = " ".join(response.text.replace("\n", " ").split())[:1000]
    return {
        "endpoint": name,
        "status": response.status_code,
        "content_type": content_type,
        "request_id": response.headers.get("x-goog-request-id")
        or response.headers.get("x-request-id")
        or response.headers.get("x-guploader-uploadid")
        or "",
        "body": body,
    }


def safe_token_info(access_token: str) -> dict:
    response = requests.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"access_token": access_token},
        timeout=30,
    )
    if not response.ok:
        return {"status": response.status_code, "detail": response.text[:500]}
    data = response.json()
    return {
        "email": data.get("email", ""),
        "scope": data.get("scope", ""),
        "expires_in": data.get("expires_in", ""),
        "verified_email": data.get("verified_email", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--output", default="google-play-diagnostic.json")
    args = parser.parse_args()

    raw = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        print("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is missing.", file=sys.stderr)
        return 2
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is invalid JSON: {exc}", file=sys.stderr)
        return 2

    credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    credentials.refresh(Request())
    token = safe_token_info(credentials.token)
    package = quote(args.package, safe="._-")
    report = {
        "identity": info.get("client_email"),
        "project_id": info.get("project_id"),
        "package_name": args.package,
        "runner": {
            "name": os.getenv("RUNNER_NAME", ""),
            "os": os.getenv("RUNNER_OS", ""),
            "architecture": os.getenv("RUNNER_ARCH", ""),
        },
        "oauth": token,
        "endpoint_probes": [],
        "success": False,
    }

    for endpoint_name, api_base in ENDPOINTS:
        session = AuthorizedSession(credentials)
        response = session.post(
            f"{api_base}/applications/{package}/edits",
            json={},
            timeout=60,
        )
        probe = compact_response(endpoint_name, response)
        report["endpoint_probes"].append(probe)
        if response.ok:
            edit_id = response.json().get("id")
            probe["edit_id_created"] = bool(edit_id)
            report["success"] = True
            report["working_endpoint"] = endpoint_name
            if edit_id:
                cleanup = session.delete(
                    f"{api_base}/applications/{package}/edits/{quote(str(edit_id), safe='._-')}",
                    timeout=60,
                )
                probe["cleanup_status"] = cleanup.status_code
            break

    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "# Google Play Cloud Diagnostic",
            "",
            f"- Identity: `{report['identity']}`",
            f"- Cloud project: `{report['project_id']}`",
            f"- Package: `{report['package_name']}`",
            f"- OAuth scope present: `{'yes' if SCOPE in str(token.get('scope', '')).split() else 'no'}`",
            f"- Result: `{'SUCCESS' if report['success'] else 'FAILED'}`",
            "",
            "| Endpoint | HTTP | Content type | Result |",
            "|---|---:|---|---|",
        ]
        for probe in report["endpoint_probes"]:
            body = probe.get("body")
            if isinstance(body, dict):
                detail = body.get("error", {}).get("message") or json.dumps(body, ensure_ascii=False)
            else:
                detail = str(body)
            detail = detail.replace("|", "\\|")[:300]
            lines.append(
                f"| {probe['endpoint']} | {probe['status']} | {probe['content_type'] or 'unknown'} | {detail} |"
            )
        Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
