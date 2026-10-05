import os,json,io,requests
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from django.core.files.base import ContentFile
from apps.publisher.models import MobileApp,Release,Submission,AppAsset
from apps.integrations.apple_store import AppleStoreClient
from apps.integrations.apple_assets import sync_app_store_screenshots
from apps.integrations.apple_compliance import apply_app_store_compliance,ensure_build_encryption_declaration
from apps.publisher.store_compliance import _BASE_BUSINESS_AGE_RATING
from apps.integrations.google_play import GooglePlayClient
from apps.integrations.base import IntegrationError
from django.utils import timezone
from PIL import Image,ImageDraw,ImageFont
a=MobileApp.objects.get(slug="be-different")
# Promotional graphic uses the real brand asset; screenshots are captured native UI.
icon=a.assets.filter(kind="icon").first()
assert icon
with Image.open(icon.file.path) as source:
 logo=source.convert("RGBA")
 for locale,tag in [("de-DE","TRAINING. REGENERATION. COACHING."),("en-US","TRAINING. RECOVERY. COACHING.")]:
  image=Image.new("RGB",(1024,500),(5,6,6))
  mark=logo.copy();mark.thumbnail((340,340));image.paste(mark,((1024-mark.width)//2,30),mark)
  draw=ImageDraw.Draw(image)
  font=ImageFont.load_default(size=25)
  draw.text((512,390),"BE DIFFERENT",font=ImageFont.load_default(size=36),fill=(255,255,255),anchor="mm")
  draw.text((512,454),tag,font=font,fill=(215,255,0),anchor="mm")
  raw=io.BytesIO();image.save(raw,format="PNG")
  asset,_=AppAsset.objects.get_or_create(app=a,kind="feature_graphic",platform="android",locale=locale,device_type="",sort_order=0,defaults={"width":1024,"height":500})
  asset.width=1024;asset.height=500;asset.file.save("be-different-feature-"+locale+".png",ContentFile(raw.getvalue()),save=True)
# Normalize only Android listing icons; preserve the original brand source.
with Image.open(icon.file.path) as source:
 normalized=source.convert("RGBA").resize((512,512),Image.Resampling.LANCZOS)
 raw=io.BytesIO();normalized.save(raw,format="PNG")
 for locale in ("de-DE","en-US"):
  asset,_=AppAsset.objects.get_or_create(app=a,kind="icon",platform="android",locale=locale,device_type="",sort_order=0,defaults={"width":512,"height":512})
  asset.width=512;asset.height=512;asset.file.save("be-different-icon-"+locale+".png",ContentFile(raw.getvalue()),save=True)
# Do not replace or withdraw a submitted Apple version.
r=Release.objects.get(pk=126,app=a,build_number=7)
client=AppleStoreClient(a.apple_account)
def full_request(method,path,**kwargs):
 headers=kwargs.pop("headers",{});headers["Authorization"]="Bearer "+client.token()
 headers.setdefault("Content-Type","application/json")
 res=requests.request(method,"https://api.appstoreconnect.apple.com/v1"+path,headers=headers,timeout=90,**kwargs)
 if not res.ok:
  safe=res.text.replace(a.get_review_password(),"[REDACTED]")
  raise IntegrationError("Apple API "+str(res.status_code)+": "+safe[:16000])
 return res.json() if res.content else {}
client.request=full_request
record=client.find_app(a.bundle_id)
version=client.request("GET","/appStoreVersions/bec48543-3f4a-47b5-9fb6-53701512abb2")["data"]
state=version["attributes"].get("appStoreState")
if state not in ("WAITING_FOR_REVIEW","IN_REVIEW","PENDING_DEVELOPER_RELEASE","READY_FOR_SALE"):
 for locale in ("de-DE","en-US"):
  assert a.assets.filter(kind="screenshot",platform="ios",locale=locale,device_type="APP_IPHONE_65").count()>=3,"Native iPhone screenshots pending"
  assert a.assets.filter(kind="screenshot",platform="ios",locale=locale,device_type="APP_WATCH_SERIES_7").exists(),"Native Watch screenshots pending"
 profile=dict(_BASE_BUSINESS_AGE_RATING)
 profile.update(ageAssurance=True,messagingAndChat=True,healthOrWellnessTopics=True)
 print("APPLE_COMPLIANCE="+json.dumps(apply_app_store_compliance(client,record["id"],content_rights="USES_THIRD_PARTY_CONTENT",age_rating=profile)))
 ensure_build_encryption_declaration(client,"e8775372-d060-47b8-bef6-ad13b9de1713",False)
 locs=[client.set_localization(version["id"],loc) for loc in a.localizations.all()]
 print("APPLE_NATIVE_ASSETS="+json.dumps(sync_app_store_screenshots(client,version["id"],locs,list(a.assets.filter(platform="ios")),timeout=360)))
 client.attach_build(version["id"],"e8775372-d060-47b8-bef6-ad13b9de1713")
 client.set_review_details(version["id"],a)
 result=client.submit_version(record["id"],version["id"])
 final=result["submission"]["attributes"]["state"]
 print("APPLE_ACTUAL_REVIEW_STATE="+final)
 assert final in ("WAITING_FOR_REVIEW","IN_REVIEW"),final
 Submission.objects.update_or_create(app=a,release=r,platform="ios",defaults={"state":"in_review","external_id":result["submission"]["id"],"submitted_at":timezone.now(),"last_error":"","raw":result})
else:print("APPLE_ACTUAL_REVIEW_STATE="+state)
# Store content is independent of APK upload. Production promotion happens only after policy setup.
g=GooglePlayClient(a.google_account)
for locale in ("de-DE","en-US"):
 assert a.assets.filter(kind="screenshot",platform="android",locale=locale).count()>=3,"Native Android screenshots pending"
print("GOOGLE_NATIVE_LISTING="+json.dumps(g.apply_store_content(a,list(a.localizations.all()),list(a.assets.filter(platform="android")))))
