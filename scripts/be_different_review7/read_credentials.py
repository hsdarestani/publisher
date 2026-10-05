import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from apps.publisher.models import MobileApp
a=MobileApp.objects.get(slug="be-different")
assert a.review_username and a.get_review_password()
print(json.dumps({"username":a.review_username,"password":a.get_review_password()}))
