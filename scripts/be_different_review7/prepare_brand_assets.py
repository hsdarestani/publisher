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
for asset in a.assets.filter(kind="feature_graphic",platform="android").order_by("locale"):
 print("FEATURE_PNG="+json.dumps({"locale":asset.locale,"data":__import__("base64").b64encode(open(asset.file.path,"rb").read()).decode()}))
g=GooglePlayClient(a.google_account)
print("GOOGLE_BRAND_LISTING="+json.dumps(g.apply_store_content(a,list(a.localizations.all()),list(a.assets.filter(platform="android")))))
