import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from django.db import transaction
from apps.publisher.models import MobileApp,Release,Build,Job
from apps.publisher.tasks import enqueue_job
with transaction.atomic():
 a=MobileApp.objects.select_for_update().get(slug="be-different")
 r,created=Release.objects.get_or_create(app=a,version_name="1.0.0",build_number=10,defaults={"source_branch":"main","source_commit":"3caa758b5f1c3617af37973c6223462696c85f17","android_track":"internal","auto_submit":False,"status":"building","release_notes":"Fix native ExpoAsset and ExpoFont startup autolinking, install navigation dependencies explicitly, and localize English tab labels."})
 assert r.source_commit=="3caa758b5f1c3617af37973c6223462696c85f17",r.source_commit
 for platform,agent_platform in (("android","linux"),("ios","macos")):
  b,_=Build.objects.get_or_create(release=r,platform=platform,defaults={"commit_sha":r.source_commit})
  j=Job.objects.filter(release=r,type="build_"+platform,status__in=["queued","running","succeeded"]).first()
  if not j:j=enqueue_job("build_"+platform,app=a,release=r,build=b,agent=True,platform=agent_platform)
  print("NATIVE_REVIEW10="+json.dumps({"platform":platform,"release":r.pk,"build":b.pk,"job":j.pk,"source":r.source_commit}))
