from __future__ import annotations

from apps.compliance.services import _console_autofill
from apps.signing.management.commands import bootstrap_a_studio as base
from apps.signing.management.commands import bootstrap_a_studio_builder as builder


class Command(builder.Command):
    help = "Prepare A+ Studio Build 10 Cloud App Builder with hardened App Store compliance metadata."

    def _upsert_compliance(self, app):
        # Call the stable base implementation directly, then apply the truthful
        # Cloud App Builder declarations. ComplianceProfile uses related_name
        # `compliance`, so avoid relying on an incorrect reverse attribute.
        base.Command._upsert_compliance(self, app)
        profile = app.compliance
        profile.purpose = (
            "Cloud-basierter App Builder: neue App-Projekte anlegen, serverseitige "
            "Erstellung verfolgen und Änderungswünsche verwalten."
        )
        profile.business_model = (
            "B2B cloud app creation service; no mobile purchase flow and no "
            "generated-app runtime in iOS"
        )
        profile.app_access = "restricted"
        profile.app_access_instructions = (
            "App Review kann über 'Demo ansehen' ohne Konto den vollständigen "
            "iOS-Builder-Ablauf prüfen. Die Demo führt keinen generierten Code aus."
        )
        profile.payment_handling = "none"
        profile.payment_details = (
            "Die iOS-App enthält keine Käufe, Abonnements oder externen Zahlungslinks."
        )
        profile.store_declarations = dict(profile.store_declarations or {})
        profile.store_declarations.update({
            "app_access": "restricted",
            "cloud_app_builder": True,
            "generated_code_executes_in_ios": False,
            "generated_app_preview_in_ios": False,
            "mobile_store_submission": False,
        })
        profile.console_autofill = _console_autofill(profile)
        profile.save()
        self.stdout.write("compliance_profile=cloud_builder_no_runtime")
