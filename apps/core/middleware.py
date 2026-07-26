import logging

from django.http import JsonResponse


logger = logging.getLogger(__name__)


class AuditRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.audit_ip = self._ip(request)
        return self.get_response(request)

    @staticmethod
    def _ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


class CloudAgentExceptionMiddleware:
    """Return a restricted diagnostic for GitHub OIDC agent failures only."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        is_cloud_claim = (
            request.path == "/apps/agent-api/claim/"
            and bool(request.headers.get("X-GitHub-OIDC", ""))
        )
        if not is_cloud_claim:
            return None

        logger.exception("A+ Cloud Mac claim failed", exc_info=exception)
        detail = str(exception).replace("\n", " ")[:1000]
        return JsonResponse(
            {
                "error": "cloud_agent_internal_error",
                "exception": type(exception).__name__,
                "detail": detail,
            },
            status=503,
        )
