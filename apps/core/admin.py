from django.contrib import admin
from .models import AuditEvent

@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "summary")
    list_filter = ("action", "created_at")
    search_fields = ("summary", "object_id")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]
