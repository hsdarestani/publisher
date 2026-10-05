import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from apps.publisher.models import MobileApp
a=MobileApp.objects.get(slug="be-different")
assert a.review_username and a.get_review_password()
data={"username":a.review_username,"password":a.get_review_password()}
def find(config,key):
 if isinstance(config,dict):
  if key in config:return config[key]
  for value in config.values():
   if isinstance(value,dict):
    got=find(value,key)
    if got:return got
 return None
for key in ("FIREBASE_ANDROID_GOOGLE_SERVICES_B64","FIREBASE_IOS_GOOGLE_SERVICE_INFO_B64"):
 value=find(a.build_config,key) or os.getenv(key)
 assert value,"Missing native capture Firebase client configuration: "+key+"; available configuration keys: "+",".join(a.build_config)
 data[key]=value
print(json.dumps(data))
