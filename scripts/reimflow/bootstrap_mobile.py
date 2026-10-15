"""Idempotently register Reimflow in A+ Publisher and queue internal mobile builds.
Run only inside the Publisher Django environment. No store uploads or public submissions.
"""
import json
import os
from django.db import transaction
from apps.publisher.models import MobileApp, StoreAccount, AppLocalization, Release, Build, Job
from apps.signing.services import ensure_android_signing, ensure_ios_signing
from apps.integrations.apple_store import AppleStoreClient

APP_ID="sbs.smarbiz.reimflow"
SOURCE="https://github.com/hsdarestani/Reimflow"
SHA=os.environ.get("REIMFLOW_SOURCE_COMMIT","").strip()
QUEUE=os.environ.get("REIMFLOW_QUEUE_BUILDS","0")=="1"
assert len(SHA)==40 and all(c in "0123456789abcdef" for c in SHA.lower()),"Verified source commit required"

def account(provider):
    accounts=[a for a in StoreAccount.objects.filter(provider=provider,enabled=True) if a.configured]
    if len(accounts)!=1:
        print("STORE_ACCOUNT_BLOCKED",provider,"count="+str(len(accounts)))
        return None
    return accounts[0]

google=account("google")
apple=account("apple")
existing=MobileApp.objects.filter(slug="reimflow").first()
collision=MobileApp.objects.filter(package_name=APP_ID).exclude(slug="reimflow").first()
if collision: raise RuntimeError("The selected Reimflow package identifier is already used by another app")
app=existing or MobileApp(slug="reimflow")
app.name="Reimflow"
app.client_name="Reimflow"
app.platform="both"
app.framework="other"
app.status="setup"
app.package_name=APP_ID
app.bundle_id=APP_ID
app.repository_url=SOURCE
app.default_branch="main"
app.tech_stack=["Capacitor 8","JavaScript","Python API","SQLite","Android","iOS"]
app.category="Music"
app.content_rating="12+"
app.requires_login=False
app.marketing_url="https://reimflow.smarbiz.sbs/"
# Do not invent legal URLs, data controllers or working support contact.
# Preserve existing verified store metadata if they were already populated.
app.google_account=app.google_account if app.google_account_id else google
app.apple_account=app.apple_account if app.apple_account_id else apple
app.build_config={
 "android_command":"bash scripts/publisher-android.sh",
 "android_artifact":"android/app/build/outputs/bundle/release/*.aab",
 "ios_command":"bash scripts/publisher-ios.sh",
 "ios_artifact":"artifacts/export/*.ipa",
}
app.latest_commit_sha=SHA
app.review_notes=(
 "Reimflow helps German-speaking rappers find phonetic rhymes and work with community "
 "content and licensed audio. Core rhyme search and rhythm game can be used without sign-in. "
 "Account login is required for posting, favoriting and saving Beats. Rap audio recording "
 "is optional and requires explicit consent before server processing. Purchases are disabled. "
 "A review account, confirmed legal links and comprehensive moderation must be supplied "
 "and checked before submitting for store review."
)
app.save()
texts={
"de-DE":{
 "title":"Reimflow",
 "subtitle":"Reime, Flow und Beats",
 "short_description":"KI Reime nach Klang, Flow Spiele und Beats für Rapper.",
 "full_description":"Finde deutsche und englische Reime anhand von Aussprache, Betonung und Silben. Suche Wortgruppen, entdecke Klangvarianten, speichere Favoriten und trainiere deinen Rhythmus mit dem Flow Spiel. Eigene Reime und selbst erstellte Beats können mit einer Community geteilt und geprüft werden. Die optionale Rap Analyse wertet freiwillig aufgenommene Sprachbeiträge aus. Keine Käufe oder Abonnements.",
 "keywords":"reime,rap,flow,beats,klang,silben,freestyle,hiphop,rapper,phonetik",
 "release_notes":"Erste Testversion: Reimsuche, Flow Spiel, Community und Beats."
},
"en-US":{
 "title":"Reimflow",
 "subtitle":"Rhymes, Flow and Beats",
 "short_description":"AI phonetic rhymes, flow games and beats for rappers.",
 "full_description":"Find German and English rhymes based on sound, stressed syllables and pronunciation. Explore multisyllabic lyric ideas, save favorites, practise timing in a rhythm game and share original rhymes or licensed audio with a moderated community. Optional rap recording analysis requires explicit consent. No purchases or subscriptions.",
 "keywords":"rhymes,rap,flow,beats,lyrics,freestyle,rhythm,syllables",
 "release_notes":"Initial internal test build: rhyme discovery, Flow Challenge, community and Beats."
}
}
for locale,values in texts.items():
    loc,_=AppLocalization.objects.get_or_create(app=app,locale=locale,defaults={"title":"Reimflow"})
    for key,val in values.items():setattr(loc,key,val)
    loc.save()
release,_=Release.objects.get_or_create(app=app,version_name="1.0.0",build_number=1,
    defaults={"status":"draft","source_branch":"main","source_commit":SHA,
        "android_track":"internal","ios_release_type":"manual","auto_submit":False,
        "release_notes":"Initial closed beta build without purchases."})
if release.source_commit != SHA and release.status not in ("draft","failed","ready"):
    raise RuntimeError("Existing version 1.0.0 (1) uses another source; refuse to overwrite build")
release.source_branch="main";release.source_commit=SHA
release.android_track="internal";release.ios_release_type="manual";release.auto_submit=False
release.save()
print("APP",json.dumps({"id":app.id,"slug":app.slug,"package":app.package_name,"bundle":app.bundle_id,"source":SHA[:12],"google_linked":bool(app.google_account_id),"apple_linked":bool(app.apple_account_id),"payment_enabled":False}))
ready={}
try:
    cert=ensure_android_signing(app)
    ready["android"]=True
    print("ANDROID_SIGNING_READY sha256="+cert.certificate_sha256)
except Exception as exc:
    ready["android"]=False
    print("ANDROID_SIGNING_BLOCKED",type(exc).__name__,str(exc)[:260])
if app.apple_account and app.apple_account.configured:
    try:
        client=AppleStoreClient(app.apple_account)
        found=client.request("GET","/bundleIds?filter[identifier]="+APP_ID+"&limit=5").get("data",[])
        if not any(a.get("attributes",{}).get("identifier")==APP_ID for a in found):
            data={"data":{"type":"bundleIds","attributes":{"identifier":APP_ID,"name":"Reimflow","platform":"IOS"}}}
            client.request("POST","/bundleIds",data=json.dumps(data))
            print("APPLE_BUNDLE_REGISTERED")
        else:print("APPLE_BUNDLE_EXISTS")
        profile=ensure_ios_signing(app)
        ready["ios"]=True
        print("IOS_SIGNING_READY profile="+profile.profile_name)
    except Exception as exc:
        ready["ios"]=False
        print("IOS_SIGNING_BLOCKED",type(exc).__name__,str(exc)[:300])
else:
    ready["ios"]=False
    print("IOS_SIGNING_BLOCKED: no configured Apple store account")
if QUEUE:
    for platform in ("android","ios"):
        if not ready.get(platform):
            print("BUILD_BLOCKED",platform,"signing unavailable")
            continue
        build,_=Build.objects.get_or_create(release=release,platform=platform,defaults={"status":"queued","commit_sha":SHA})
        if build.status=="succeeded" and build.artifact and build.commit_sha==SHA:
            print("BUILD_ALREADY_SUCCEEDED",platform,build.id)
            continue
        existing=Job.objects.filter(release=release,build=build,type="build_"+platform,status__in=("queued","running")).first()
        if existing:
            print("BUILD_ALREADY_QUEUED",platform,existing.id)
            continue
        build.status="queued";build.commit_sha=SHA
        build.save(update_fields=["status","commit_sha","updated_at"])
        job=Job.objects.create(type="build_"+platform,app=app,release=release,build=build,
            payload={"source":"reimflow-internal-beta","source_commit":SHA},
            available_to_agents=True,
            required_platform="linux" if platform=="android" else "macos")
        print("BUILD_QUEUED",platform,job.id)
    release.status="building"
    release.save(update_fields=["status","updated_at"])
else: print("BUILDS_NOT_QUEUED")
print("LEGAL_BLOCKERS",json.dumps({"privacy_url":bool(app.privacy_policy_url),"support_url":bool(app.support_url),"review_credentials":bool(app.review_username and app.review_password_blob),"ios_screenshots":app.assets.filter(kind="screenshot",platform="ios").count(),"android_screenshots":app.assets.filter(kind="screenshot",platform="android").count()}))
