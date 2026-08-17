#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_BUNDLE_ID="de.aplussolution.samscard"
EXPECTED_TEAM_ID="884MVA2MD5"
EXPECTED_VERSION="1.0.4"
EXPECTED_BUILD="2026081701"

: "${IOS_BUNDLE_ID:?IOS_BUNDLE_ID is required}"
: "${IOS_TEAM_ID:?IOS_TEAM_ID is required}"
: "${APP_VERSION_NAME:?APP_VERSION_NAME is required}"
: "${APP_BUILD_NUMBER:?APP_BUILD_NUMBER is required}"
: "${IOS_PROVISIONING_PROFILE_SPECIFIER:?IOS_PROVISIONING_PROFILE_SPECIFIER is required}"

[ "$IOS_BUNDLE_ID" = "$EXPECTED_BUNDLE_ID" ] || { echo "REFUSE_WRONG_BUNDLE=$IOS_BUNDLE_ID" >&2; exit 31; }
[ "$IOS_TEAM_ID" = "$EXPECTED_TEAM_ID" ] || { echo "REFUSE_WRONG_TEAM=$IOS_TEAM_ID" >&2; exit 32; }
[ "$APP_VERSION_NAME" = "$EXPECTED_VERSION" ] || { echo "REFUSE_WRONG_VERSION=$APP_VERSION_NAME" >&2; exit 33; }
[ "$APP_BUILD_NUMBER" = "$EXPECTED_BUILD" ] || { echo "REFUSE_WRONG_BUILD=$APP_BUILD_NUMBER" >&2; exit 34; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOBILE="$ROOT/sams-ios-release/mobile"
ARTIFACT_DIR="$ROOT/sams-ios-release/artifacts"

[ -f "$MOBILE/capacitor.config.ts" ] || { echo "Sams Capacitor config missing" >&2; exit 35; }
grep -Fq "appId: 'de.aplussolution.samscard'" "$MOBILE/capacitor.config.ts"
grep -Fq "appName: 'Sams Club Lounge'" "$MOBILE/capacitor.config.ts"
grep -Fq "url: 'https://app.samsclublounge.de'" "$MOBILE/capacitor.config.ts"

echo "SAMS_BUILD_IDENTITY_OK version=$APP_VERSION_NAME build=$APP_BUILD_NUMBER bundle=$IOS_BUNDLE_ID"

XCODE_APP="$(find /Applications -maxdepth 1 -type d -name 'Xcode_26*.app' -print 2>/dev/null | sort -V | tail -n 1 || true)"
if [ -n "$XCODE_APP" ]; then
  sudo xcode-select -s "$XCODE_APP/Contents/Developer"
fi
xcodebuild -version
IOS_SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version)"
IOS_SDK_MAJOR="${IOS_SDK_VERSION%%.*}"
[ "$IOS_SDK_MAJOR" -ge 26 ] || { echo "iOS SDK 26+ required, got $IOS_SDK_VERSION" >&2; exit 36; }

export IOS_VERSION_NAME="$APP_VERSION_NAME"
export IOS_BUILD_NUMBER="$APP_BUILD_NUMBER"
export IOS_PROVISIONING_PROFILE_NAME="$IOS_PROVISIONING_PROFILE_SPECIFIER"

pushd "$MOBILE" >/dev/null
npm install --no-audit --no-fund
rm -rf ios
npx cap add ios
npx cap sync ios
npx @capacitor/assets generate --ios --assetPath assets \
  --iconBackgroundColor '#09050f' --iconBackgroundColorDark '#09050f' \
  --splashBackgroundColor '#09050f' --splashBackgroundColorDark '#09050f'
popd >/dev/null

sudo gem install xcodeproj --no-document
ruby "$MOBILE/ci/prepare-ios-release.rb"

/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$MOBILE/ios/App/App/Info.plist" | grep -Fx 'Sams Club Lounge'
grep -Fq 'PRODUCT_BUNDLE_IDENTIFIER = de.aplussolution.samscard' "$MOBILE/ios/App/App.xcodeproj/project.pbxproj"
grep -Fq 'app.samsclublounge.de' "$MOBILE/ios/App/App/App.entitlements"
grep -Fq 'SamsVerificationUniversalLinkRouter' "$MOBILE/ios/App/App/AppDelegate.swift"

git config --global http.version HTTP/1.1
SOURCE_PACKAGES_DIR="${RUNNER_TEMP:-/tmp}/SAMS-SourcePackages"
rm -rf "$SOURCE_PACKAGES_DIR"
mkdir -p "$SOURCE_PACKAGES_DIR"

if [ -d "$MOBILE/ios/App/App.xcworkspace" ]; then
  XCODE_CONTAINER=(-workspace "$MOBILE/ios/App/App.xcworkspace")
else
  XCODE_CONTAINER=(-project "$MOBILE/ios/App/App.xcodeproj")
fi

for ATTEMPT in 1 2 3 4 5; do
  echo "SAMS_SWIFTPM_ATTEMPT=$ATTEMPT"
  if xcodebuild -resolvePackageDependencies \
      "${XCODE_CONTAINER[@]}" \
      -scheme App \
      -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
      -scmProvider system; then
    break
  fi
  [ "$ATTEMPT" -lt 5 ] || exit 74
  rm -rf "$SOURCE_PACKAGES_DIR/artifacts"
  find "$SOURCE_PACKAGES_DIR" -name '*.download' -delete 2>/dev/null || true
  sleep $((ATTEMPT * 20))
done

ARCHIVE_PATH="${RUNNER_TEMP:-/tmp}/SAMSClubLounge.xcarchive"
rm -rf "$ARCHIVE_PATH"
xcodebuild \
  "${XCODE_CONTAINER[@]}" \
  -scheme App \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE_PATH" \
  -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
  -disableAutomaticPackageResolution \
  archive

ARCHIVE_INFO="$ARCHIVE_PATH/Info.plist"
[ -f "$ARCHIVE_INFO" ] || { echo "Archive Info.plist missing" >&2; exit 37; }
ARCHIVE_APP_REL="$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:ApplicationPath' "$ARCHIVE_INFO")"
ARCHIVE_APP="$ARCHIVE_PATH/Products/$ARCHIVE_APP_REL"
ARCHIVE_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:CFBundleIdentifier' "$ARCHIVE_INFO")"
[ "$ARCHIVE_BUNDLE_ID" = "$EXPECTED_BUNDLE_ID" ] || { echo "Archive has wrong bundle: $ARCHIVE_BUNDLE_ID" >&2; exit 38; }
[ -f "$ARCHIVE_APP/Info.plist" ] || { echo "Archived app Info.plist missing: $ARCHIVE_APP/Info.plist" >&2; exit 40; }
/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$ARCHIVE_APP/Info.plist" | grep -Fx 'Sams Club Lounge'
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$ARCHIVE_APP/Info.plist" | grep -Fx "$EXPECTED_VERSION"
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$ARCHIVE_APP/Info.plist" | grep -Fx "$EXPECTED_BUILD"
ENTITLEMENTS_PLIST="${RUNNER_TEMP:-/tmp}/sams-entitlements.plist"
codesign -d --entitlements :- "$ARCHIVE_APP" >"$ENTITLEMENTS_PLIST" 2>/dev/null
grep -Fq 'app.samsclublounge.de' "$ENTITLEMENTS_PLIST"
grep -Fq '884MVA2MD5.de.aplussolution.samscard' "$ENTITLEMENTS_PLIST"

EXPORT_PATH="${RUNNER_TEMP:-/tmp}/SAMSClubLoungeExport"
EXPORT_OPTIONS="${RUNNER_TEMP:-/tmp}/SAMSExportOptions.plist"
rm -rf "$EXPORT_PATH"
cat > "$EXPORT_OPTIONS" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>manual</string>
  <key>signingCertificate</key><string>Apple Distribution</string>
  <key>teamID</key><string>${IOS_TEAM_ID}</string>
  <key>provisioningProfiles</key>
  <dict><key>${IOS_BUNDLE_ID}</key><string>${IOS_PROVISIONING_PROFILE_SPECIFIER}</string></dict>
  <key>manageAppVersionAndBuildNumber</key><false/>
  <key>stripSwiftSymbols</key><true/>
  <key>uploadSymbols</key><true/>
</dict>
</plist>
PLIST

xcodebuild -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS"

IPA_PATH="$(find "$EXPORT_PATH" -maxdepth 1 -name '*.ipa' -print -quit)"
[ -n "$IPA_PATH" ] && [ -s "$IPA_PATH" ] || { echo "Sams IPA export missing" >&2; exit 39; }
mkdir -p "$ARTIFACT_DIR"
cp "$IPA_PATH" "$ARTIFACT_DIR/sams-club-lounge.ipa"
shasum -a 256 "$ARTIFACT_DIR/sams-club-lounge.ipa"
echo "SAMS_IPA_READY=$ARTIFACT_DIR/sams-club-lounge.ipa"
