set -euo pipefail
apk="$(find previous -name app-release.apk -print -quit)"
test -n "$apk"
adb install "$apk"
mkdir -p screenshots
adb logcat -c
if ! maestro test -e REVIEW_USER="$REVIEW_USER" -e REVIEW_PASS="$REVIEW_PASS" -e SHOTDIR="$PWD/screenshots" scripts/be_different_review7/android.yaml; then
  adb exec-out screencap -p > screenshots/android-failure.png
  adb logcat -d -s ReactNativeJS AndroidRuntime | tail -n 120
  adb shell uiautomator dump /sdcard/bd-ui.xml >/dev/null
  adb shell cat /sdcard/bd-ui.xml
  exit 1
fi
