// Textos do fork (inglês). Mesclados no i18n do upstream por ./index.ts.
const en = {
  customFixedSlicePrinter: { chooseNozzle: 'Choose the nozzle' },
  customNativePlate: { title: 'Build plate check', preview: 'Native camera', calibrate: 'Save empty plate reference' },
  customPlateRoi: {
    backdrop: 'Empty plate (reference)', corner: 'Corner {{n}}', fine: 'Fine adjust of the selected corner',
    nudge: 'Move selected corner', reset: 'Reset',
    instruction: 'Drag the 4 corners to the plate edges; drag the middle to move the area. Tap a corner and use the arrows to fine-tune.',
  },
  customModelAppearance: {
    label: 'Model appearance', colored: 'Color', white: 'White', previewColors: 'Preview colors',
  },
  customPrintHistory: {
    history: 'History', files: 'Files', calendar: 'Calendar', filters: 'Filters', sort: 'Sort',
    ascending: 'Sort ascending', descending: 'Sort descending',
    untitled: 'Job #{{id}}', beforeStart: 'Before printing', queueRecord: 'Queue record',
    loadFailed: 'Could not load print history.',
    removeQueueConfirm: 'Remove this job from the queue history?',
  },
  notifications: {
    providerTypes: { webpush: 'Web Push (PWA)' },
    providerDescriptions: {
      webpush:
        'Native notifications on phones/computers where Bambuddy is installed as an app. Enable each device under Settings → Notifications → "Notifications on this device". Sends to all enabled devices.',
    },
  },
  customWebPush: {
    title: 'Notifications on this device',
    description: 'Get Bambuddy alerts on this phone or computer, even with the app closed.',
    status: {
      checking: 'Checking…',
      unsupported: 'This browser does not support push notifications.',
      insecure: 'Push needs HTTPS. Open Bambuddy through its https:// address (not an IP or http://).',
      iosInstall: 'On iPhone/iPad, first add Bambuddy to the Home Screen (Share → Add to Home Screen) and open it from there.',
      backendOff: 'Push is disabled on this server.',
      denied: 'Notifications are blocked for this site. Allow them in the browser/app settings and reload.',
      off: 'Off on this device.',
      on: 'On: this device receives notifications.',
    },
    deniedHelp:
      'Android: app info for Bambuddy (long-press the icon → App info) → Notifications → Allow. In Chrome: lock icon in the address bar → Permissions → Notifications.',
    enable: 'Enable on this device',
    disable: 'Disable',
    test: 'Send test',
    testSent: 'Test sent to {{count}} device(s).',
    testFailed: 'Test failed: {{error}}',
    devices: '{{count}} device(s) enabled on your account',
    noProvider:
      'No enabled "Web Push (PWA)" channel yet: Bambuddy events only reach this device once that channel exists.',
    createProvider: 'Create Web Push channel (recommended events)',
    providerCreated: 'Channel created. Adjust events under Providers.',
    providerName: 'Phone (Web Push)',
    bannerText: 'Get print alerts on this device?',
    bannerEnable: 'Enable',
    bannerDismiss: 'Not now',
    error: 'Error: {{error}}',
  },
  custom: {
    prefs: {
      speedMode1: 'Silent ({{percent}}%)',
      speedMode2: 'Normal ({{percent}}%)',
      speedMode3: 'Fast ({{percent}}%)',
      speedMode4: 'Super-fast ({{percent}}%)',
      speedMode5: 'Ultra-fast ({{percent}}%)',
      speedCustom: 'Custom ({{percent}}%)',
      nozzleTitle: 'Configured nozzle (tap to change)',
      nozzleHint: 'Which nozzle is installed?',
      nozzleBusy: 'The nozzle cannot be changed while printing',
      nozzleSet: 'Nozzle set: {{d}} mm',
      speedDefaultTitle: 'Speed for the next print',
      speedNowHint: 'Changes now',
      speedNextHint: 'Applies to the next print, from layer {{layer}}',
      speedNow: 'Speed: {{mode}}',
      speedNext: 'Next print at {{mode}}',
    },
  },
};

export default en;
