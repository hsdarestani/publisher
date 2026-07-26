from django.contrib import admin
from .models import MetricPoint, TechnicalIssue, RepositorySnapshot, ReportSync
admin.site.register(MetricPoint)
admin.site.register(TechnicalIssue)
admin.site.register(RepositorySnapshot)
admin.site.register(ReportSync)
