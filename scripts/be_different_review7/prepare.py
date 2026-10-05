import os,json,secrets,requests
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from apps.publisher.models import MobileApp,Release,AppLocalization
from apps.integrations.apple_store import AppleStoreClient
a=MobileApp.objects.get(slug="be-different")
r=Release.objects.get(pk=126,app=a,build_number=7)
assert r.builds.filter(platform="ios",status="succeeded").exists()
if not a.review_username:
    a.review_username="appreview@bedifferent.smarbiz.sbs"
if not a.get_review_password():
    a.set_review_password(secrets.token_urlsafe(24))
a.requires_login=True
a.review_notes="Review account is a dedicated fictional athlete. Sign in using the supplied credentials; no email verification or two factor authentication is required. Onboarding is already completed. Open START for the performance score, TRAINING for plans, FORTSCHRITT for progress, ATHLET for profile and settings. Health access is optional and disabled for this review account. Different AI is available from the athlete profile. Data completeness is shown honestly when health sources are not connected. Optional wearable providers require the user's own provider account. No purchase is required to use the supplied review account."
a.save(update_fields=["review_username","review_password_blob","requires_login","review_notes","updated_at"])
session=requests.Session()
base="https://bedifferent.smarbiz.sbs"
session.headers.update({"x-bd-client":"mobile","content-type":"application/json","origin":base})
auth={"email":a.review_username,"password":a.get_review_password()}
res=session.post(base+"/api/auth/login",json=auth,timeout=40)
if res.status_code==401:
    res=session.post(base+"/api/auth/register",json={**auth,"name":"Review Athlete"},timeout=40)
res.raise_for_status()
token=res.json().get("sessionToken")
assert token,"Mobile review session missing"
session.headers["Authorization"]="Bearer "+token
d=session.get(base+"/api/mobile/dashboard",timeout=40)
d.raise_for_status()
if not d.json()["user"]["onboardingCompleted"]:
    res=session.post(base+"/api/onboarding/complete",json={"goal":"Athletik","birthDate":"2000-01-01","sex":"prefer_not_to_say","heightCm":180,"weightKg":80,"trainingExperience":"STARTER","availabilityPerWeek":3,"healthConsent":False,"privacyConsent":True,"termsConsent":True},timeout=40)
    res.raise_for_status()
session.post(base+"/api/auth/logout",json={},timeout=30).raise_for_status()
descriptions={
 "de-DE":{"title":"BE DIFFERENT","subtitle":"Training und Regeneration","short_description":"Training, Regeneration und Coaching für deine sportliche Entwicklung.","full_description":"BE DIFFERENT verbindet Training, Regeneration und persönliche Betreuung in einem System.\n\nVerfolge deinen Leistungswert und die Vollständigkeit deiner Daten. Plane dein Training, protokolliere Übungen und verfolge deine Fortschritte. Tageschecks, Ernährung und Regeneration helfen dir, deinen Alltag bewusster zu gestalten.\n\nNutze die Übungsbibliothek, kommuniziere mit deinem Trainer und erhalte Unterstützung durch Different AI. Unterstützte Gesundheitsdaten und Wearables kannst du freiwillig verbinden. Ohne Verbindung bleiben fehlende Daten sichtbar.\n\nDeine Daten kontrollierst du selbst: Einstellungen, Datenexport und Kontolöschung sind in deinem Konto verfügbar. Gesundheitsdaten werden nur mit deiner Einwilligung verarbeitet. Die App bietet Trainings und Lifestyle Unterstützung und ersetzt keine medizinische Diagnose oder Behandlung.","keywords":"Training,Fitness,Regeneration,Coaching,Athletik,Fortschritt","release_notes":"Erste Version mit Training, Leistungswert, Regeneration und Coaching."},
 "en-US":{"title":"BE DIFFERENT","subtitle":"Training. Recovery. Coaching.","short_description":"Training, recovery and coaching for your athletic development.","full_description":"BE DIFFERENT brings training, recovery and personal coaching together.\n\nFollow your performance score and data completeness. Plan your training, log exercises and track progress. Daily check ins, nutrition and recovery tools support informed everyday decisions.\n\nExplore the exercise library, communicate with your coach and get assistance from Different AI. Connect supported health data sources and wearables voluntarily. Missing data remains visible when a source is not connected.\n\nControl your data through account settings, data export and account deletion. Health data is processed with your consent. The app provides training and lifestyle support and does not replace medical diagnosis or treatment.","keywords":"training,fitness,recovery,coaching,athlete,progress","release_notes":"Initial release with training, performance score, recovery and coaching."}
}
for locale,attrs in descriptions.items():
    AppLocalization.objects.update_or_create(app=a,locale=locale,defaults=attrs)
c=AppleStoreClient(a.apple_account)
record=c.find_app(a.bundle_id)
v=c.ensure_version(record["id"],r.version_name)
c.request("PATCH",f"/appStoreVersions/{v['id']}",data=json.dumps({"data":{"type":"appStoreVersions","id":v["id"],"attributes":{"copyright":"2026 BE DIFFERENT"}}}))
from apps.integrations.apple_compliance import find_editable_app_info
info=find_editable_app_info(c,record["id"])
info_locs=c.request("GET",f"/appInfos/{info['id']}/appInfoLocalizations?limit=200").get("data",[])
for loc in a.localizations.all():
    existing=next((x for x in info_locs if x["attributes"].get("locale")==loc.locale),None)
    attrs={"privacyPolicyUrl":a.privacy_policy_url,"subtitle":loc.subtitle}
    if existing:
        c.request("PATCH",f"/appInfoLocalizations/{existing['id']}",data=json.dumps({"data":{"type":"appInfoLocalizations","id":existing["id"],"attributes":attrs}}))
    else:
        attrs.update({"locale":loc.locale,"name":"BE DIFFERENT Training"})
        c.request("POST","/appInfoLocalizations",data=json.dumps({"data":{"type":"appInfoLocalizations","attributes":attrs,"relationships":{"appInfo":{"data":{"type":"appInfos","id":info["id"]}}}}}))
    c.set_localization(v["id"],loc)
detail=c.request("GET",f"/appStoreVersions/{v['id']}/appStoreReviewDetail").get("data")
contact={}
existing=(detail or {}).get("attributes",{})
defaults={"contactFirstName":"Ashkan","contactLastName":"Asadian","contactPhone":"+491727779721","contactEmail":"info@aplus-solution.de"}
for key,value in defaults.items():
    if not existing.get(key):contact[key]=value
c.set_review_details(v["id"],a,contact=contact or None)
print("REVIEW_PREPARATION_OK: login verified; de-DE/en-US metadata saved; copyright and review details saved")
