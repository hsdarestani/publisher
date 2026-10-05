import os,json,requests
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from apps.publisher.models import MobileApp
a=MobileApp.objects.get(slug="be-different")
s=requests.Session()
base="https://bedifferent.smarbiz.sbs"
s.headers.update({"x-bd-client":"mobile","origin":base})
r=s.post(base+"/api/auth/login",json={"email":a.review_username,"password":a.get_review_password()},timeout=40);r.raise_for_status()
s.headers["Authorization"]="Bearer "+r.json()["sessionToken"]
r=s.post(base+"/api/companion/pair/start",timeout=40);r.raise_for_status()
claim=s.post(base+"/api/companion/pair/claim",json={"code":r.json()["code"]},timeout=40);claim.raise_for_status()
token=claim.json()["sessionToken"]
check=requests.get(base+"/api/companion",headers={"Authorization":"Bearer "+token,"x-bd-client":"watch"},timeout=40)
check.raise_for_status()
assert check.json().get("ok")
print(json.dumps({"token":token}))
s.post(base+"/api/auth/logout",timeout=30).raise_for_status()
