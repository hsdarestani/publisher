from .models import AuditEvent

def log_event(request, action: str, summary: str, obj=None, metadata=None):
    AuditEvent.objects.create(
        actor=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(getattr(obj, "pk", "")) if obj else "",
        summary=summary,
        metadata=metadata or {},
        ip_address=getattr(request, "audit_ip", None),
    )
