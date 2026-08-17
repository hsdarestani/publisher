import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'de.aplussolution.samscard',
  appName: 'Sams Club Lounge',
  webDir: 'www',
  backgroundColor: '#05030b',
  server: {
    url: 'https://app.samsclublounge.de',
    cleartext: false,
    allowNavigation: ['app.samsclublounge.de'],
  },
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert', 'banner', 'list'],
    },
  },
  ios: {
    contentInset: 'never',
    preferredContentMode: 'mobile',
    zoomEnabled: false,
  },
  android: {
    allowMixedContent: false,
    adjustMarginsForEdgeToEdge: 'force',
  },
};

export default config;
