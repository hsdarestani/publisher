from django.db import migrations


def set_review_login(apps, schema_editor):
    # Use the dedicated seeded demo account only. It contains no real customer data.
    # This credential is intentionally review-only and can be rotated after launch.
    from apps.publisher.models import MobileApp

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        return
    app.review_username = 'demo@a-esthetic.de'
    app.set_review_password('Aplus-Demo-2026!')
    app.review_notes = (
        'Review-only demo account for the A+ Esthetic Customer Club. '
        'No real customer data is used.'
    )
    app.save(update_fields=['review_username', 'review_password_blob', 'review_notes', 'updated_at'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0009_report_a_esthetic_state'),
    ]

    operations = [
        migrations.RunPython(set_review_login, noop_reverse),
    ]
