#!/usr/bin/env ruby
# frozen_string_literal: true

require 'fileutils'
require 'xcodeproj'

required = %w[IOS_BUNDLE_ID IOS_TEAM_ID IOS_VERSION_NAME IOS_BUILD_NUMBER IOS_PROVISIONING_PROFILE_NAME]
required.each do |name|
  value = ENV[name]
  abort("Missing required environment variable: #{name}") if value.nil? || value.strip.empty?
end

abort('Wrong Sams bundle ID') unless ENV['IOS_BUNDLE_ID'] == 'de.aplussolution.samscard'
abort('Wrong Apple Team') unless ENV['IOS_TEAM_ID'] == '884MVA2MD5'
abort('Wrong Sams release version') unless ENV['IOS_VERSION_NAME'] == '1.0.4'
abort('Wrong Sams build number') unless ENV['IOS_BUILD_NUMBER'] == '2026081701'

mobile_root = File.expand_path('..', __dir__)
ios_root = File.join(mobile_root, 'ios', 'App')
project_path = File.join(ios_root, 'App.xcodeproj')
app_dir = File.join(ios_root, 'App')
info_plist_path = File.join(app_dir, 'Info.plist')
entitlements_path = File.join(app_dir, 'App.entitlements')
app_delegate_path = File.join(app_dir, 'AppDelegate.swift')
launch_storyboard_path = File.join(app_dir, 'Base.lproj', 'LaunchScreen.storyboard')
privacy_source = File.join(mobile_root, 'ci', 'PrivacyInfo.xcprivacy')
privacy_target = File.join(app_dir, 'PrivacyInfo.xcprivacy')

[project_path, info_plist_path, app_delegate_path, launch_storyboard_path, privacy_source].each do |path|
  abort("Required Sams iOS release file missing: #{path}") unless File.exist?(path)
end

launch = File.read(launch_storyboard_path)
dark = '<color key="backgroundColor" red="0.0196078431" green="0.0117647059" blue="0.0431372549" alpha="1" colorSpace="custom" customColorSpace="sRGB"/>'
patched_launch = launch.gsub(/<color key="backgroundColor"[^>]*\/>/, dark)
File.write(launch_storyboard_path, patched_launch)

entitlements = {
  'aps-environment' => 'production',
  'com.apple.developer.associated-domains' => [
    'applinks:app.samsclublounge.de',
    'webcredentials:app.samsclublounge.de'
  ],
  'com.apple.developer.applesignin' => ['Default']
}
Xcodeproj::Plist.write_to_path(entitlements, entitlements_path)
FileUtils.cp(privacy_source, privacy_target)

info = Xcodeproj::Plist.read_from_path(info_plist_path)
background_modes = Array(info['UIBackgroundModes'])
background_modes << 'remote-notification' unless background_modes.include?('remote-notification')
info['UIBackgroundModes'] = background_modes
info['UIViewControllerBasedStatusBarAppearance'] = false
info['UIStatusBarStyle'] = 'UIStatusBarStyleLightContent'
info['CFBundleDisplayName'] = 'Sams Club Lounge'
info['CFBundleDevelopmentRegion'] = 'de'
info['CFBundleLocalizations'] = ['de']
info['NSCameraUsageDescription'] = 'Die Kamera wird ausschließlich zum Scannen der QR-Mitgliedskarte verwendet.'
info['NSPhotoLibraryUsageDescription'] = 'Die Fotomediathek wird nur geöffnet, wenn du ausdrücklich ein Bild zur Verwendung in der App auswählst.'
info['NSPhotoLibraryAddUsageDescription'] = 'Ein Bild wird nur auf deinen ausdrücklichen Wunsch in deiner Fotomediathek gespeichert.'
info['NSFaceIDUsageDescription'] = 'Face ID wird verwendet, um den geschützten Verwaltungszugriff bequem und sicher zu bestätigen.'
info['ITSAppUsesNonExemptEncryption'] = false
Xcodeproj::Plist.write_to_path(info, info_plist_path)

File.write(app_delegate_path, <<~'SWIFT')
  import UIKit
  import WebKit
  import Capacitor

  @UIApplicationMain
  class AppDelegate: UIResponder, UIApplicationDelegate {
      var window: UIWindow?

      func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
          return true
      }

      func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
          return ApplicationDelegateProxy.shared.application(app, open: url, options: options)
      }

      func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
          let proxyResult = ApplicationDelegateProxy.shared.application(application, continue: userActivity, restorationHandler: restorationHandler)
          if let url = SamsVerificationUniversalLinkRouter.verificationURL(from: userActivity) {
              SamsVerificationUniversalLinkRouter.route(url, in: window)
              return true
          }
          return proxyResult
      }

      func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
          NotificationCenter.default.post(name: .capacitorDidRegisterForRemoteNotifications, object: deviceToken)
      }

      func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
          NotificationCenter.default.post(name: .capacitorDidFailToRegisterForRemoteNotifications, object: error)
      }
  }

  private enum SamsVerificationUniversalLinkRouter {
      static func verificationURL(from userActivity: NSUserActivity) -> URL? {
          guard userActivity.activityType == NSUserActivityTypeBrowsingWeb,
                let url = userActivity.webpageURL,
                url.scheme?.lowercased() == "https",
                url.host?.lowercased() == "app.samsclublounge.de",
                url.path.hasPrefix("/accounts/verify/") else {
              return nil
          }
          return url
      }

      static func route(_ url: URL, in window: UIWindow?, attempt: Int = 0) {
          guard attempt < 40 else { return }
          DispatchQueue.main.async {
              guard let bridgeViewController = window?.rootViewController as? CAPBridgeViewController,
                    let webView = bridgeViewController.webView else {
                  DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                      SamsVerificationUniversalLinkRouter.route(url, in: window, attempt: attempt + 1)
                  }
                  return
              }
              if webView.url != url {
                  webView.load(URLRequest(url: url))
              }
          }
      }
  }
SWIFT

project = Xcodeproj::Project.open(project_path)
target = project.targets.find { |candidate| candidate.name == 'App' }
abort('Xcode target App not found') unless target

privacy_ref = project.files.find { |file| ['PrivacyInfo.xcprivacy', 'App/PrivacyInfo.xcprivacy'].include?(file.path) }
privacy_ref ||= project.main_group.new_file('App/PrivacyInfo.xcprivacy')
unless target.resources_build_phase.files_references.include?(privacy_ref)
  target.resources_build_phase.add_file_reference(privacy_ref, true)
end

target.build_configurations.each do |configuration|
  settings = configuration.build_settings
  settings['PRODUCT_BUNDLE_IDENTIFIER'] = ENV.fetch('IOS_BUNDLE_ID')
  settings['DEVELOPMENT_TEAM'] = ENV.fetch('IOS_TEAM_ID')
  settings['CODE_SIGN_STYLE'] = 'Manual'
  settings['CODE_SIGN_IDENTITY'] = 'Apple Distribution'
  settings['PROVISIONING_PROFILE_SPECIFIER'] = ENV.fetch('IOS_PROVISIONING_PROFILE_NAME')
  settings['CODE_SIGN_ENTITLEMENTS'] = 'App/App.entitlements'
  settings['MARKETING_VERSION'] = ENV.fetch('IOS_VERSION_NAME')
  settings['CURRENT_PROJECT_VERSION'] = ENV.fetch('IOS_BUILD_NUMBER')
  settings['PRODUCT_NAME'] = 'Sams Club Lounge'
  settings['TARGETED_DEVICE_FAMILY'] = '1'
end

project.save
puts "Prepared Sams Club Lounge #{ENV.fetch('IOS_VERSION_NAME')} (#{ENV.fetch('IOS_BUILD_NUMBER')}) for #{ENV.fetch('IOS_BUNDLE_ID')}"
