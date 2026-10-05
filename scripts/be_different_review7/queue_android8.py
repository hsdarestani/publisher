import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from django.db import transaction
from apps.publisher.models import MobileApp,Release,Build,Job
from apps.publisher.tasks import enqueue_job
with transaction.atomic():
 a=MobileApp.objects.select_for_update().get(slug="be-different")
 r,created=Release.objects.get_or_create(app=a,version_name="1.0.0",build_number=8,defaults={"source_branch":"main","source_commit":"9bd4c707beaf0adb665c8e3d9bd029511045c3e0","android_track":"internal","auto_submit":False,"status":"building","release_notes":"Correct explicit optional Health Connect read permissions and remove unused background media playback permission."})
 assert r.source_commit=="9bd4c707beaf0adb665c8e3d9bd029511045c3e0",r.source_commit
 b,_=Build.objects.get_or_create(release=r,platform="android",defaults={"commit_sha":r.source_commit})
 j=Job.objects.filter(release=r,type="build_android",status__in=["queued","running","succeeded"]).first()
 if not j:j=enqueue_job("build_android",app=a,release=r,build=b,agent=True,platform="linux")
 print("ANDROID_REVIEW8="+json.dumps({"release":r.pk,"build":b.pk,"job":j.pk,"source":r.source_commit}))
