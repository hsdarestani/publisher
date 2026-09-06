from django.db import migrations


SOURCE_COMMIT = '9bd756581438b97377b9e80a927c34e9272e8cf0'
RELEASE_NOTES = (
    'Dienstplan auf Mobilgeräten verbessert: Notizen bleiben beim Öffnen der Tastatur '
    'auf Android und iOS vollständig sichtbar. Die Formularhöhe reagiert jetzt auf den '
    'tatsächlich sichtbaren Bildschirmbereich.'
)


def queue_keyboard_fix_release(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppLocalization = apps.get_model('publisher', 'AppLocalization')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-plus-solution').first()
    if not app:
        return
    if not app.google_account_id or not app.apple_account_id or not app.repository_url:
        return

    cfg = dict(app.build_config or {})
    cfg['android_command'] = 'bash frontend/scripts/build-publisher-android.sh'
    cfg['android_artifact'] = 'frontend/android/app/build/outputs/bundle/release/*.aab'
    cfg['ios_command'] = 'bash frontend/scripts/build-publisher-ios-opaque.sh'
    cfg['ios_artifact'] = 'frontend/ios/build/export/*.ipa'
    env = dict(cfg.get('env') or {})
    env['VITE_API_URL'] = 'https://solution.smarbiz.sbs/api'
    cfg['env'] = env
    app.build_config = cfg
    app.requires_login = True
    app.review_notes = (
        'A+ Solution is the internal workforce application used by A+ Solution GmbH. '
        'This update fixes keyboard avoidance in the mobile shift editor on Android and iOS: '
        'the note field remains visible while typing and the form follows the usable viewport. '
        'The supplied App Review account is a dedicated active employee test account. '
        'There are no in-app purchases.'
    )
    app.save(update_fields=['build_config', 'requires_login', 'review_notes', 'updated_at'])

    localization = AppLocalization.objects.filter(app=app, locale='de-DE').first()
    if localization:
        localization.release_notes = (
            'Dienstplan verbessert: Notizen bleiben beim Tippen auf Android und iOS '
            'vollständig oberhalb der Tastatur sichtbar.'
        )
        localization.save(update_fields=['release_notes', 'updated_at'])

    latest = Release.objects.filter(app=app).order_by('-build_number', '-created_at').first()
    version_name = latest.version_name if latest and latest.version_name else '1.0.9'
    db_max = max(Release.objects.filter(app=app).values_list('build_number', flat=True), default=0)
    build_number = max(int(db_max) + 1, 22)

    release, _ = Release.objects.get_or_create(
        app=app,
        version_name=version_name,
        build_number=build_number,
    )
    release.status = 'building'
    release.source_branch = 'main'
    release.source_commit = SOURCE_COMMIT
    release.android_track = 'production'
    release.android_rollout = 1
    release.ios_release_type = 'automatic'
    release.auto_submit = True
    release.release_notes = RELEASE_NOTES
    release.save(update_fields=[
        'status', 'source_branch', 'source_commit', 'android_track',
        'android_rollout', 'ios_release_type', 'auto_submit', 'release_notes',
        'updated_at',
    ])

    for platform, job_type, runner in (
        ('android', 'build_android', 'linux'),
        ('ios', 'build_ios', 'macos'),
    ):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == 'succeeded' and build.artifact:
            continue
        if Job.objects.filter(
            release=release,
            build=build,
            type=job_type,
            status__in=['queued', 'running', 'succeeded'],
        ).exists():
            continue

        build.status = 'queued'
        build.logs = ''
        build.external_build_id = ''
        build.metadata = {}
        build.save(update_fields=[
            'status', 'logs', 'external_build_id', 'metadata', 'updated_at'
        ])

        Job.objects.create(
            type=job_type,
            app=app,
            release=release,
            build=build,
            payload={
                'source': 'shift-note-keyboard-safe-20260906',
                'source_commit': SOURCE_COMMIT,
            },
            available_to_agents=True,
            required_platform=runner,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0018_queue_aplus_solution_scroll_fix_release'),
    ]

    operations = [
        migrations.RunPython(queue_keyboard_fix_release, noop_reverse),
    ]
