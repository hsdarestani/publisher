import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from django.db import transaction
from apps.publisher.models import MobileApp,Release,Build,Job
from django.utils import timezone
with transaction.atomic():
 a=MobileApp.objects.get(slug="be-different")
 old=Job.objects.select_for_update().get(pk=3662,app=a,release_id=128,type="build_ios")
 b=Build.objects.select_for_update().get(pk=229,release_id=128,platform="ios")
 assert not b.artifact,"An existing signed artifact must not be modified"
 assert old.status in ("running","failed"),old.status
 if old.status=="running":
  old.status="failed"
  old.error="GitHub worker 37359193973 terminated after HTTP 502 at ios-signing and completion endpoints during Publisher restart. Corrected build 10 is queued."
  old.save(update_fields=["status","error","updated_at"])
  b.status="failed";b.save(update_fields=["status","updated_at"])
 r=Release.objects.get(pk=129,app=a,build_number=10)
 new=Job.objects.get(pk=3665,release=r,type="build_ios")
 print("VERIFIED_QUEUE_RECOVERY="+json.dumps({"old_job":old.pk,"old_state":old.status,"new_job":new.pk,"new_state":new.status}))
