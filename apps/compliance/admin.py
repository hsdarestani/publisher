from django.contrib import admin

from .models import ComplianceProfile, ComplianceRun


@admin.register(ComplianceProfile)
class ComplianceProfileAdmin(admin.ModelAdmin):
    list_display = ("app", "status", "confidence", "ai_used", "last_generated_at", "last_applied_at")
    list_filter = ("status", "ai_used", "has_ads", "app_access")
    search_fields = ("app__name", "app__package_name", "purpose")
    readonly_fields = ("companion_token", "created_at", "updated_at")


@admin.register(ComplianceRun)
class ComplianceRunAdmin(admin.ModelAdmin):
    list_display = ("profile", "action", "status", "progress", "created_at", "finished_at")
    list_filter = ("action", "status")
    search_fields = ("profile__app__name", "error", "logs")
