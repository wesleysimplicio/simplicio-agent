import { defineFieldCopy } from '@/app/settings/field-copy'

import { defineLocale } from './define-locale'

// Arabic (CLDR) plural rule: zero / one / two / few (n%100 = 3-10) / many (n%100 = 11-99) / other.
function arPlural(
  n: number,
  forms: { zero?: string; one: string; two: string; few: string; many: string; other: string }
): string {
  const mod100 = n % 100
  if (n === 0) return forms.zero ?? forms.other
  if (n === 1) return forms.one
  if (n === 2) return forms.two
  if (mod100 >= 3 && mod100 <= 10) return forms.few
  if (mod100 >= 11 && mod100 <= 99) return forms.many
  return forms.other
}

export const ar = defineLocale({
  common: {
    apply: 'تطبيق',
    back: 'رجوع',
    save: 'حفظ',
    saving: 'جارٍ الحفظ…',
    cancel: 'إلغاء',
    change: 'تغيير',
    choose: 'اختيار',
    clear: 'مسح',
    close: 'إغلاق',
    collapse: 'طي',
    confirm: 'تأكيد',
    connect: 'اتصال',
    connecting: 'جارٍ الاتصال',
    continue: 'متابعة',
    copied: 'تم النسخ',
    copy: 'نسخ',
    copyFailed: 'فشل النسخ',
    delete: 'حذف',
    docs: 'الوثائق',
    done: 'تم',
    error: 'خطأ',
    failed: 'فشل',
    free: 'مجاني',
    loading: 'جارٍ التحميل…',
    notSet: 'غير محدد',
    refresh: 'تحديث',
    remove: 'إزالة',
    replace: 'استبدال',
    retry: 'إعادة المحاولة',
    run: 'تشغيل',
    send: 'إرسال',
    set: 'تعيين',
    skip: 'تخطي',
    update: 'تحديث',
    on: 'تشغيل',
    off: 'إيقاف'
  },

  fileMenu: {
    revealFinder: 'إظهار في Finder',
    revealExplorer: 'إظهار في مستكشف الملفات',
    revealFileManager: 'فتح المجلد الحاوي',
    revealInSidebar: 'إظهار في شجرة الملفات',
    copyPath: 'نسخ المسار',
    copyRelativePath: 'نسخ المسار النسبي',
    rename: 'إعادة تسمية…',
    delete: 'حذف',
    renameTitle: 'إعادة تسمية',
    renameLabel: 'الاسم الجديد',
    deleteTitle: name => `حذف ${name}؟`,
    deleteBody: 'سيُنقل إلى سلة المهملات — يمكنك استعادته من هناك.',
    pathCopied: 'تم نسخ المسار'
  },

  boot: {
    ready: 'سطح مكتب Simplicio جاهز',
    desktopBootFailedWithMessage: message => `فشل تشغيل سطح المكتب: ${message}`,
    steps: {
      connectingGateway: 'جارٍ الاتصال ببوابة سطح المكتب المباشرة',
      loadingSettings: 'جارٍ تحميل إعدادات Simplicio',
      loadingSessions: 'جارٍ تحميل الجلسات الأخيرة',
      startingDesktopConnection: 'جارٍ بدء اتصال سطح المكتب',
      startingHermesDesktop: 'جارٍ تشغيل Simplicio Desktop…'
    },
    errors: {
      backgroundExited: 'توقفت عملية Simplicio الخلفية.',
      backgroundExitedDuringStartup: 'توقفت عملية Simplicio الخلفية أثناء بدء التشغيل.',
      backendStopped: 'توقف الخادم الخلفي',
      desktopBootFailed: 'فشل تشغيل سطح المكتب',
      gatewayConnectionLost: 'انقطع الاتصال بالبوابة',
      gatewaySignInRequired: 'يلزم تسجيل الدخول إلى البوابة',
      ipcBridgeUnavailable: 'جسر IPC الخاص بسطح المكتب غير متاح.'
    },
    failure: {
      title: 'تعذّر بدء تشغيل Simplicio',
      description:
        'لم تُشغَّل البوابة الخلفية. جرّب إحدى خطوات الاستعادة أدناه. لن يؤدي أي منها إلى حذف محادثاتك أو إعداداتك.',
      remoteTitle: 'يلزم تسجيل الدخول إلى البوابة البعيدة',
      remoteDescription:
        'انتهت صلاحية جلسة البوابة البعيدة. سجّل الدخول مجددًا لإعادة الاتصال. لن يؤدي أي شيء هنا إلى حذف محادثاتك أو إعداداتك.',
      retry: 'إعادة المحاولة',
      repairInstall: 'إصلاح التثبيت',
      useLocalGateway: 'استخدام البوابة المحلية',
      openLogs: 'فتح السجلات',
      repairHint: 'يعيد الإصلاح تشغيل المثبِّت وقد يستغرق بضع دقائق على جهاز جديد.',
      remoteSignInHint: 'يفتح نافذة تسجيل الدخول إلى البوابة. استخدم البوابة المحلية للتبديل إلى الخادم المدمج بدلًا من ذلك.',
      hideRecentLogs: 'إخفاء السجلات الأخيرة',
      showRecentLogs: 'إظهار السجلات الأخيرة',
      signedInTitle: 'تم تسجيل الدخول',
      signedInMessage: 'جارٍ إعادة الاتصال بالبوابة البعيدة…',
      signInIncompleteTitle: 'تسجيل الدخول غير مكتمل',
      signInIncompleteMessage: 'أُغلقت نافذة تسجيل الدخول قبل اكتمال المصادقة.',
      signInFailed: 'فشل تسجيل الدخول',
      signInToRemoteGateway: 'تسجيل الدخول إلى البوابة البعيدة',
      signInWithProvider: provider => `تسجيل الدخول باستخدام ${provider}`,
      identityProvider: 'مزوّد الهوية الخاص بك'
    }
  },

  notifications: {
    region: 'الإشعارات',
    hide: 'إخفاء',
    show: 'إظهار',
    more: count =>
      arPlural(count, {
        one: 'إشعار واحد إضافي',
        two: 'إشعاران إضافيان',
        few: `${count} إشعارات إضافية`,
        many: `${count} إشعارًا إضافيًا`,
        other: `${count} إشعار إضافي`
      }),
    clearAll: 'مسح الكل',
    dismiss: 'إغلاق الإشعار',
    details: 'التفاصيل',
    copyDetail: 'نسخ التفاصيل',
    copyDetailFailed: 'تعذّر نسخ تفاصيل الإشعار',
    backendOutOfDateTitle: 'الخادم الخلفي قديم',
    backendOutOfDateMessage:
      'خادم Simplicio الخلفي أقدم من إصدار سطح المكتب هذا وقد لا يعمل بشكل صحيح. حدّثه ليتوافق معه.',
    updateHermes: 'تحديث Simplicio',
    updateReadyTitle: 'التحديث جاهز',
    updateReadyMessage: count =>
      arPlural(count, {
        one: 'يتوفر تغيير واحد جديد.',
        two: 'يتوفر تغييران جديدان.',
        few: `تتوفر ${count} تغييرات جديدة.`,
        many: `يتوفر ${count} تغييرًا جديدًا.`,
        other: `يتوفر ${count} تغيير جديد.`
      }),
    seeWhatsNew: 'عرض الجديد',
    errors: {
      elevenLabsNeedsKey: 'يحتاج ElevenLabs STT إلى ELEVENLABS_API_KEY.',
      elevenLabsRejectedKey: 'رفض ElevenLabs مفتاح الواجهة البرمجية (401).',
      methodNotAllowed: 'رفض الخادم الخلفي لسطح المكتب هذا الطلب (405 Method Not Allowed). جرّب إعادة تشغيل Simplicio Desktop.',
      microphonePermission: 'رُفض إذن الميكروفون.',
      openaiRejectedApiKey: 'رفض OpenAI مفتاح الواجهة البرمجية.',
      openaiRejectedApiKeyWithStatus: status => `رفض OpenAI مفتاح الواجهة البرمجية (${status} invalid_api_key).`,
      openaiTtsNeedsKey: 'يحتاج OpenAI TTS إلى VOICE_TOOLS_OPENAI_KEY أو OPENAI_API_KEY.'
    },
    voice: {
      configureSpeechToText: 'اضبط تحويل الكلام إلى نص لاستخدام وضع الصوت.',
      couldNotStartSession: 'تعذّر بدء الجلسة الصوتية',
      microphoneAccessDenied: 'رُفض الوصول إلى الميكروفون.',
      microphoneConstraintsUnsupported: 'قيود الميكروفون غير مدعومة على هذا الجهاز.',
      microphoneFailed: 'فشل الميكروفون',
      microphoneInUse: 'الميكروفون قيد الاستخدام من تطبيق آخر.',
      microphonePermissionDenied: 'رُفض إذن الميكروفون.',
      microphoneStartFailed: 'تعذّر بدء تسجيل الميكروفون.',
      microphoneUnsupported: 'بيئة التشغيل هذه لا تدعم تسجيل الميكروفون.',
      noMicrophone: 'لم يُعثر على أي ميكروفون.',
      noSpeechDetected: 'لم يُكتشف أي كلام',
      playbackFailed: 'فشل تشغيل الصوت',
      recordingFailed: 'فشل تسجيل الصوت',
      transcriptionFailed: 'فشل تفريغ الصوت',
      transcriptionUnavailable: 'تفريغ الصوت غير متاح بعد.',
      tryRecordingAgain: 'جرّب التسجيل مرة أخرى.',
      unavailable: 'الصوت غير متاح'
    },
    native: {
      approvalTitle: 'يلزم الموافقة',
      approveAction: 'موافقة',
      rejectAction: 'رفض',
      inputTitle: 'مطلوب إدخال',
      inputBody: 'ينتظر Simplicio ردّك.',
      turnDoneTitle: 'أنهى Simplicio العمل',
      turnDoneBody: 'الرد جاهز.',
      turnErrorTitle: 'فشلت الجولة',
      backgroundDoneTitle: 'انتهت المهمة الخلفية',
      backgroundFailedTitle: 'فشلت المهمة الخلفية'
    }
  },

  remoteDisplayBanner: {
    message: reason => `التصيير البرمجي نشط — تم اكتشاف شاشة عرض بعيدة (${reason}). عُطِّل تسريع الرسوميات GPU لمنع الوميض.`,
    dismiss: 'إغلاق'
  },

  titlebar: {
    hideSidebar: 'إخفاء الشريط الجانبي',
    showSidebar: 'إظهار الشريط الجانبي',
    search: 'بحث',
    searchTitle: 'البحث في الجلسات والعروض والإجراءات',
    swapSidebarSides: 'تبديل جهتي الشريط الجانبي',
    swapSidebarSidesTitle: 'تبديل جهتي الجلسات ومستعرض الملفات',
    hideRightSidebar: 'إخفاء الشريط الجانبي الأيمن',
    showRightSidebar: 'إظهار الشريط الجانبي الأيمن',
    muteHaptics: 'كتم التنبيهات اللمسية',
    unmuteHaptics: 'إلغاء كتم التنبيهات اللمسية',
    openSettings: 'فتح الإعدادات',
    openStarmap: 'فتح خريطة الذاكرة',
    openKeybinds: 'اختصارات لوحة المفاتيح'
  },

  keybinds: {
    title: 'اختصارات لوحة المفاتيح',
    subtitle: open => `انقر على اختصار لإعادة ربطه · ${open} تعيد فتح هذه اللوحة.`,
    rebind: 'إعادة ربط',
    reset: 'إعادة الضبط الافتراضي',
    resetAll: 'إعادة ضبط الكل',
    pressKey: 'اضغط على مفتاح…',
    set: 'تعيين',
    conflictWith: label => `مرتبط أيضًا بـ「${label}」`,
    categories: {
      composer: 'الكتابة',
      profiles: 'الملفات الشخصية',
      session: 'الجلسة',
      navigation: 'التنقل',
      view: 'العرض'
    },
    actions: {
      'keybinds.openPanel': 'فتح اختصارات لوحة المفاتيح',
      'nav.commandPalette': 'فتح لوحة الأوامر',
      'nav.commandCenter': 'فتح مركز الأوامر',
      'nav.settings': 'فتح الإعدادات',
      'nav.profiles': 'فتح الملفات الشخصية',
      'nav.skills': 'فتح المهارات',
      'nav.messaging': 'فتح المراسلة',
      'nav.artifacts': 'فتح المخرجات',
      'nav.cron': 'فتح المهام المجدولة',
      'nav.agents': 'فتح الوكلاء',
      'session.new': 'جلسة جديدة',
      'session.newWindow': 'جلسة جديدة في نافذة',
      'session.next': 'الجلسة التالية',
      'session.prev': 'الجلسة السابقة',
      'session.slot.1': 'التبديل إلى الجلسة الأخيرة 1',
      'session.slot.2': 'التبديل إلى الجلسة الأخيرة 2',
      'session.slot.3': 'التبديل إلى الجلسة الأخيرة 3',
      'session.slot.4': 'التبديل إلى الجلسة الأخيرة 4',
      'session.slot.5': 'التبديل إلى الجلسة الأخيرة 5',
      'session.slot.6': 'التبديل إلى الجلسة الأخيرة 6',
      'session.slot.7': 'التبديل إلى الجلسة الأخيرة 7',
      'session.slot.8': 'التبديل إلى الجلسة الأخيرة 8',
      'session.slot.9': 'التبديل إلى الجلسة الأخيرة 9',
      'session.focusSearch': 'البحث في الجلسات',
      'session.togglePin': 'تثبيت / إلغاء تثبيت الجلسة الحالية',
      'workspace.newWorktree': 'شجرة عمل جديدة',
      'composer.focus': 'التركيز على مربع الكتابة',
      'composer.modelPicker': 'فتح مُنتقي النماذج',
      'composer.voice': 'بدء / إيقاف المحادثة الصوتية',
      'view.toggleSidebar': 'إظهار/إخفاء شريط الجلسات',
      'view.toggleRightSidebar': 'إظهار/إخفاء مستعرض الملفات',
      'view.toggleReview': 'إظهار/إخفاء لوحة المراجعة',
      'view.showFiles': 'إظهار مستعرض الملفات',
      'view.showTerminal': 'إظهار/إخفاء الطرفية',
      'view.newTerminal': 'طرفية جديدة',
      'view.nextTerminal': 'الطرفية التالية',
      'view.prevTerminal': 'الطرفية السابقة',
      'view.closeTerminal': 'إغلاق الطرفية',
      'view.terminalSelection': 'إرسال تحديد الطرفية إلى مربع الكتابة',
      'view.closePreviewTab': 'إغلاق تبويب المعاينة',
      'view.flipPanes': 'تبديل جهتي الشريط الجانبي',
      'appearance.toggleMode': 'التبديل بين الوضع الفاتح والداكن',
      'profile.default': 'التبديل إلى الملف الافتراضي',
      'profile.switch.1': 'التبديل إلى الملف الشخصي 1',
      'profile.switch.2': 'التبديل إلى الملف الشخصي 2',
      'profile.switch.3': 'التبديل إلى الملف الشخصي 3',
      'profile.switch.4': 'التبديل إلى الملف الشخصي 4',
      'profile.switch.5': 'التبديل إلى الملف الشخصي 5',
      'profile.switch.6': 'التبديل إلى الملف الشخصي 6',
      'profile.switch.7': 'التبديل إلى الملف الشخصي 7',
      'profile.switch.8': 'التبديل إلى الملف الشخصي 8',
      'profile.switch.9': 'التبديل إلى الملف الشخصي 9',
      'profile.switch.10': 'التبديل إلى الملف الشخصي 10',
      'profile.switch.11': 'التبديل إلى الملف الشخصي 11',
      'profile.switch.12': 'التبديل إلى الملف الشخصي 12',
      'profile.switch.13': 'التبديل إلى الملف الشخصي 13',
      'profile.switch.14': 'التبديل إلى الملف الشخصي 14',
      'profile.switch.15': 'التبديل إلى الملف الشخصي 15',
      'profile.switch.16': 'التبديل إلى الملف الشخصي 16',
      'profile.switch.17': 'التبديل إلى الملف الشخصي 17',
      'profile.switch.18': 'التبديل إلى الملف الشخصي 18',
      'profile.next': 'الملف الشخصي التالي',
      'profile.prev': 'الملف الشخصي السابق',
      'profile.toggleAll': 'إظهار/إخفاء عرض كل الملفات الشخصية',
      'profile.create': 'إنشاء ملف شخصي',
      'composer.send': 'إرسال الرسالة',
      'composer.newline': 'إدراج سطر جديد',
      'composer.steer': 'توجيه الجولة الجارية',
      'composer.sendQueued': 'إرسال الدور التالي في قائمة الانتظار',
      'composer.mention': 'الإشارة إلى ملفات ومجلدات وروابط',
      'composer.slash': 'لوحة أوامر الشرطة المائلة',
      'composer.help': 'مساعدة سريعة',
      'composer.history': 'التنقل بين النوافذ المنبثقة / السجل',
      'composer.cancel': 'إغلاق النافذة المنبثقة · إلغاء التشغيل'
    }
  },

  language: {
    label: 'اللغة',
    description: 'اختر لغة واجهة سطح المكتب.',
    saving: 'جارٍ حفظ اللغة…',
    saveError: 'فشل تحديث اللغة',
    switchTo: 'تغيير اللغة',
    searchPlaceholder: 'ابحث عن لغة…',
    noResults: 'لم يُعثر على أي لغة'
  },

  settings: {
    closeSettings: 'إغلاق الإعدادات',
    exportConfig: 'تصدير الإعدادات',
    importConfig: 'استيراد الإعدادات',
    resetToDefaults: 'إعادة الضبط الافتراضي',
    resetConfirm: 'إعادة ضبط كل الإعدادات إلى افتراضيات Simplicio؟',
    exportFailed: 'فشل التصدير',
    resetFailed: 'فشلت إعادة الضبط',
    nav: {
      providers: 'المزوّدون',
      providerAccounts: 'الحسابات',
      providerApiKeys: 'مفاتيح API',
      gateway: 'البوابة',
      apiKeys: 'الأدوات والمفاتيح',
      keysTools: 'الأدوات',
      keysSettings: 'الإعدادات',
      mcp: 'MCP',
      archivedChats: 'المحادثات المؤرشفة',
      about: 'حول',
      notifications: 'الإشعارات'
    },
    notifications: {
      title: 'الإشعارات',
      intro:
        'إشعارات سطح مكتب أصلية، منفصلة عن الإشعارات المنبثقة داخل التطبيق. هذه الإعدادات محلية للجهاز — يحتفظ كل حاسوب بإعداداته الخاصة.',
      enableAll: 'تفعيل الإشعارات',
      enableAllDesc: 'المفتاح الرئيسي. أوقفه لكتم كل الإشعارات أدناه.',
      focusedHint: 'تُطلَق تنبيهات الإنجاز فقط أثناء عمل Simplicio في الخلفية.',
      kinds: {
        approval: {
          label: 'يلزم الموافقة',
          description: 'ينتظر أمر ما موافقتك أو رفضك.'
        },
        input: {
          label: 'مطلوب إدخال',
          description: 'طرح Simplicio سؤالًا أو يحتاج إلى كلمة مرور أو سرّ.'
        },
        turnDone: {
          label: 'الرد جاهز',
          description: 'انتهت جولة أثناء عمل Simplicio في الخلفية.'
        },
        turnError: {
          label: 'فشلت الجولة',
          description: 'انتهت جولة بخطأ.'
        },
        backgroundDone: {
          label: 'انتهت المهمة الخلفية',
          description: 'اكتمل أمر طرفية يعمل في الخلفية.'
        }
      },
      test: 'إرسال إشعار تجريبي',
      testTitle: 'Simplicio',
      testBody: 'الإشعارات تعمل.',
      testSent: 'أُرسل الاختبار. إذا لم يظهر شيء، تحقق من أذونات إشعارات النظام ووضع عدم الإزعاج.',
      testUnsupported: 'هذا النظام لا يدعم الإشعارات الأصلية.',
      completionSoundTitle: 'صوت الإنجاز',
      completionSoundDesc: 'يُشغَّل عند انتهاء جولة الوكيل. اختر نمطًا جاهزًا وجرّبه هنا.',
      completionSoundPreview: 'معاينة'
    },
    sections: {
      model: 'النموذج',
      chat: 'المحادثة',
      appearance: 'المظهر',
      workspace: 'مساحة العمل',
      safety: 'الأمان',
      memory: 'الذاكرة والسياق',
      voice: 'الصوت',
      advanced: 'متقدم'
    },
    searchPlaceholder: {
      about: 'حول Simplicio Desktop',
      config: 'البحث في الإعدادات...',
      gateway: 'اتصال البوابة...',
      keys: 'البحث في مفاتيح API...',
      mcp: 'البحث في خوادم MCP...',
      sessions: 'البحث في الجلسات المؤرشفة...'
    },
    modeOptions: {
      light: { label: 'فاتح', description: 'أسطح سطح مكتب مشرقة' },
      dark: { label: 'داكن', description: 'مساحة عمل منخفضة الوهج' },
      system: { label: 'النظام', description: 'اتباع مظهر النظام' }
    },
    appearance: {
      title: 'المظهر',
      intro:
        'هذه تفضيلات عرض خاصة بسطح المكتب فقط. يتحكم الوضع في السطوع؛ وتتحكم السمة في لوحة الألوان وتنسيق سطح المحادثة.',
      colorMode: 'وضع الألوان',
      colorModeDesc: 'اختر وضعًا ثابتًا أو دع Simplicio يتبع إعداد نظامك.',
      toolViewTitle: 'عرض استدعاء الأداة',
      toolViewDesc: 'يخفي "المنتج" حمولات الأداة الخام؛ ويعرض "التقني" الإدخال/الإخراج الكامل.',
      translucencyTitle: 'شفافية النافذة',
      translucencyDesc: 'شاهد سطح مكتبك عبر النافذة بأكملها. لنظامي macOS وWindows فقط.',
      embedsTitle: 'التضمينات المضمّنة',
      embedsDesc:
        'تُحمَّل المعاينات الغنية من مواقع خارجية (YouTube وX و...). يعرض "اسأل" عنصرًا نائبًا حتى تسمح بكل موقع؛ ويحمّلها "دائمًا" تلقائيًا؛ ويبقي "إيقاف" الروابط نصية بسيطة.',
      embedsAsk: 'اسأل',
      embedsAlways: 'دائمًا',
      embedsOff: 'إيقاف',
      embedsReset: (count: number) =>
        arPlural(count, {
          one: 'إعادة ضبط خدمة واحدة مسموح بها',
          two: 'إعادة ضبط خدمتين مسموح بهما',
          few: `إعادة ضبط ${count} خدمات مسموح بها`,
          many: `إعادة ضبط ${count} خدمة مسموح بها`,
          other: `إعادة ضبط ${count} خدمة مسموح بها`
        }),
      product: 'المنتج',
      productDesc: 'نشاط أداة سهل الفهم مع ملخصات موجزة.',
      technical: 'تقني',
      technicalDesc: 'يشمل وسيطات ونتائج الأداة الخام والتفاصيل منخفضة المستوى.',
      themeTitle: 'السمة',
      themeDesc: 'لوحات سطح المكتب فقط. يُطبَّق الوضع المحدد فوقها.',
      themeProfileNote: profile => `محفوظة للملف الشخصي ${profile} — يحتفظ كل ملف شخصي بسمته الخاصة.`,
      installTitle: 'التثبيت من VS Code',
      installDesc:
        'الصق معرّف إضافة من المتجر (مثل dracula-theme.theme-dracula) لتحويل سمة ألوانها إلى لوحة سطح مكتب.',
      installPlaceholder: 'publisher.extension',
      installButton: 'تثبيت',
      installing: 'جارٍ التثبيت…',
      installError: 'تعذّر تثبيت هذه السمة.',
      installed: name => `تم تثبيت 「${name}」.`,
      removeTheme: 'إزالة السمة',
      importedBadge: 'مستوردة',
      pet: {
        title: 'الحيوان الأليف',
        intro:
          'تبنَّ تميمة متحركة من petdex تطفو فوق التطبيق وتتفاعل مع ما يفعله Simplicio — تجري أثناء تنفيذ الأدوات، وتحتفل عند النجاح، وتحزن عند الأخطاء.',
        restartHint:
          'تحتاج الحيوانات الأليفة إلى إعادة تشغيل سريعة — بدأ التطبيق العامل قبل إضافة هذه الميزة. أغلق Simplicio وأعد فتحه، ثم عد إلى هنا.',
        on: 'تشغيل',
        off: 'إيقاف',
        scaleTitle: 'الحجم',
        scaleDesc: 'غيّر حجم التميمة العائمة. يُطبَّق في كل مكان فورًا.',
        roamTitle: 'التجوال',
        roamDesc: 'اسمح للحيوان الأليف بالتجول في النافذة من تلقاء نفسه أثناء الخمول.',
        chooseTitle: 'اختر حيوانًا أليفًا',
        chooseDesc: 'اختيار أحدها يثبّته (إن لزم) ويجعله نشطًا.',
        searchPlaceholder: 'ابحث عن حيوانات أليفة…',
        unreachable: 'تعذّر الوصول إلى معرض petdex. تحقق من اتصالك وأعد فتح هذه الصفحة.',
        noMatch: query => `لا توجد حيوانات أليفة مطابقة لـ"${query}".`,
        installedTag: 'مثبَّت',
        generatedTag: 'مُولَّد',
        countCapped: (cap, total) => `يعرض ${cap} من ${total} — اكتب للتضييق.`,
        count: n =>
          arPlural(n, {
            one: 'حيوان أليف واحد.',
            two: 'حيوانان أليفان.',
            few: `${n} حيوانات أليفة.`,
            many: `${n} حيوانًا أليفًا.`,
            other: `${n} حيوان أليف.`
          }),
        uninstall: name => `إلغاء تثبيت ${name}`,
        delete: name => `حذف ${name}`,
        deleteTitle: name => `حذف ${name}؟`,
        deleteBody: 'سيؤدي هذا إلى حذف الحيوان الأليف نهائيًا — ولن يمكن إعادة تثبيته.',
        deleteConfirm: 'حذف',
        rename: name => `إعادة تسمية ${name}`,
        renameTitle: 'إعادة تسمية الحيوان الأليف',
        renamePlaceholder: 'سمِّ حيوانك الأليف',
        renameSave: 'حفظ',
        exportPet: name => `تصدير ${name}`,
        adoptFailed: slug => `تعذّر تبنّي ${slug}`,
        uninstallFailed: slug => `تعذّر إلغاء تثبيت ${slug}`,
        renameFailed: slug => `تعذّر إعادة تسمية ${slug}`,
        exportFailed: slug => `تعذّر تصدير ${slug}`,
        noneAvailable: 'لا تتوفر حيوانات أليفة للتفعيل الآن.',
        turnOnFailed: 'تعذّر تفعيل الحيوان الأليف.',
        turnOffFailed: 'تعذّر إيقاف الحيوان الأليف.'
      }
    },
    fieldLabels: defineFieldCopy({
      model: 'النموذج الافتراضي',
      modelContextLength: 'نافذة السياق',
      fallbackProviders: 'النماذج الاحتياطية',
      toolsets: 'مجموعات الأدوات المفعّلة',
      timezone: 'المنطقة الزمنية',
      display: {
        personality: 'الشخصية',
        showReasoning: 'كتل التفكير'
      },
      agent: {
        maxTurns: 'الحد الأقصى لخطوات الوكيل',
        imageInputMode: 'مرفقات الصور',
        apiMaxRetries: 'محاولات إعادة اتصال API',
        serviceTier: 'مستوى الخدمة',
        toolUseEnforcement: 'فرض استخدام الأداة'
      },
      terminal: {
        cwd: 'مجلد العمل',
        backend: 'خلفية التنفيذ',
        timeout: 'مهلة الأمر',
        persistentShell: 'الصدفة الدائمة',
        envPassthrough: 'تمرير متغيرات البيئة',
        dockerImage: 'صورة Docker',
        singularityImage: 'صورة Singularity',
        modalImage: 'صورة Modal',
        daytonaImage: 'صورة Daytona'
      },
      fileReadMaxChars: 'حد قراءة الملف',
      toolOutput: {
        maxBytes: 'حد مخرجات الطرفية',
        maxLines: 'حد صفحة الملف',
        maxLineLength: 'حد طول السطر'
      },
      codeExecution: {
        mode: 'وضع تنفيذ الشيفرة'
      },
      approvals: {
        mode: 'وضع الموافقة',
        timeout: 'مهلة الموافقة',
        mcpReloadConfirm: 'تأكيد إعادة تحميل MCP'
      },
      commandAllowlist: 'قائمة الأوامر المسموح بها',
      security: {
        redactSecrets: 'إخفاء الأسرار',
        allowPrivateUrls: 'السماح بعناوين URL الخاصة'
      },
      browser: {
        allowPrivateUrls: 'عناوين URL الخاصة للمتصفح',
        autoLocalForPrivateUrls: 'المتصفح المحلي لعناوين URL الخاصة'
      },
      checkpoints: {
        enabled: 'نقاط استعادة الملفات',
        maxSnapshots: 'حد نقاط الاستعادة'
      },
      voice: {
        recordKey: 'اختصار الصوت',
        maxRecordingSeconds: 'أقصى مدة تسجيل',
        autoTts: 'قراءة الردود بصوت عالٍ'
      },
      stt: {
        enabled: 'تحويل الكلام إلى نص',
        provider: 'مزوّد تحويل الكلام إلى نص',
        local: {
          model: 'نموذج التفريغ المحلي',
          language: 'لغة التفريغ'
        },
        openai: {
          model: 'نموذج OpenAI STT'
        },
        groq: {
          model: 'نموذج Groq STT'
        },
        mistral: {
          model: 'نموذج Mistral STT'
        },
        elevenlabs: {
          modelId: 'نموذج ElevenLabs STT',
          languageCode: 'لغة ElevenLabs',
          tagAudioEvents: 'وسم أحداث الصوت',
          diarize: 'تمييز المتحدثين'
        }
      },
      tts: {
        provider: 'مزوّد تحويل النص إلى كلام',
        edge: {
          voice: 'صوت Edge'
        },
        openai: {
          model: 'نموذج OpenAI TTS',
          voice: 'صوت OpenAI'
        },
        elevenlabs: {
          voiceId: 'صوت ElevenLabs',
          modelId: 'نموذج ElevenLabs'
        },
        xai: {
          voiceId: 'صوت xAI (Grok)',
          language: 'لغة xAI'
        },
        minimax: {
          model: 'نموذج MiniMax TTS',
          voiceId: 'صوت MiniMax'
        },
        mistral: {
          model: 'نموذج Mistral TTS',
          voiceId: 'صوت Mistral'
        },
        gemini: {
          model: 'نموذج Gemini TTS',
          voice: 'صوت Gemini'
        },
        neutts: {
          model: 'نموذج NeuTTS',
          device: 'جهاز NeuTTS'
        },
        kittentts: {
          model: 'نموذج KittenTTS',
          voice: 'صوت KittenTTS'
        },
        piper: {
          voice: 'صوت Piper'
        }
      },
      memory: {
        memoryEnabled: 'الذاكرة الدائمة',
        userProfileEnabled: 'الملف الشخصي للمستخدم',
        memoryCharLimit: 'ميزانية الذاكرة',
        userCharLimit: 'ميزانية الملف الشخصي',
        provider: 'مزوّد الذاكرة'
      },
      context: {
        engine: 'محرك السياق'
      },
      compression: {
        enabled: 'الضغط التلقائي',
        threshold: 'عتبة الضغط',
        targetRatio: 'هدف الضغط',
        protectLastN: 'الرسائل الأخيرة المحمية'
      },
      delegation: {
        model: 'نموذج الوكيل الفرعي',
        provider: 'مزوّد الوكيل الفرعي',
        maxIterations: 'حد جولات الوكيل الفرعي',
        maxConcurrentChildren: 'الوكلاء الفرعيون المتزامنون',
        childTimeoutSeconds: 'مهلة الوكيل الفرعي',
        reasoningEffort: 'جهد تفكير الوكيل الفرعي'
      },
      updates: {
        nonInteractiveLocalChanges: 'التغييرات المحلية عند التحديث داخل التطبيق'
      }
    }),
    fieldDescriptions: defineFieldCopy({
      model: 'يُستخدم للمحادثات الجديدة ما لم تختر نموذجًا آخر في مربع الكتابة.',
      modelContextLength: 'اتركه عند 0 لاستخدام نافذة السياق المكتشفة تلقائيًا للنموذج المحدد.',
      fallbackProviders: 'إدخالات احتياطية بصيغة provider:model تُجرَّب إذا فشل النموذج الافتراضي.',
      display: {
        personality: 'أسلوب المساعد الافتراضي للجلسات الجديدة.',
        showReasoning: 'إظهار أقسام التفكير عندما يوفرها الخادم الخلفي.'
      },
      timezone: 'تُستخدم عندما يحتاج Simplicio إلى سياق الوقت المحلي. اتركها فارغة لاستخدام المنطقة الزمنية للنظام.',
      agent: {
        imageInputMode: 'يتحكم في كيفية إرسال مرفقات الصور إلى النموذج.',
        maxTurns: 'الحد الأعلى لجولات استدعاء الأدوات قبل أن يوقف Simplicio التشغيل.'
      },
      terminal: {
        cwd: 'المجلد الافتراضي لعمل الأداة والطرفية.',
        persistentShell: 'الحفاظ على حالة الصدفة بين الأوامر عندما يدعم ذلك الخادم الخلفي.',
        envPassthrough: 'متغيرات البيئة التي تُمرَّر إلى تنفيذ الأداة.',
        dockerImage: 'صورة الحاوية المستخدمة عندما تكون خلفية التنفيذ Docker.',
        singularityImage: 'الصورة المستخدمة عندما تكون خلفية التنفيذ Singularity.',
        modalImage: 'الصورة المستخدمة عندما تكون خلفية التنفيذ Modal.',
        daytonaImage: 'الصورة المستخدمة عندما تكون خلفية التنفيذ Daytona.'
      },
      codeExecution: {
        mode: 'مدى صرامة تقييد تنفيذ الشيفرة بالمشروع الحالي.'
      },
      fileReadMaxChars: 'أقصى عدد أحرف يمكن أن يقرأها Simplicio من طلب ملف واحد.',
      approvals: {
        mode: 'كيفية تعامل Simplicio مع الأوامر التي تحتاج إلى موافقة صريحة.',
        timeout: 'المدة التي تنتظرها طلبات الموافقة قبل انتهاء المهلة.'
      },
      security: {
        redactSecrets: 'إخفاء الأسرار المكتشفة عن المحتوى المرئي للنموذج قدر الإمكان.'
      },
      checkpoints: {
        enabled: 'إنشاء لقطات للتراجع قبل تعديل الملفات.'
      },
      memory: {
        memoryEnabled: 'حفظ ذكريات دائمة يمكن أن تساعد الجلسات المستقبلية.',
        userProfileEnabled: 'الحفاظ على ملف تعريف مختصر لتفضيلات المستخدم.'
      },
      context: {
        engine: 'استراتيجية إدارة المحادثات الطويلة القريبة من حد السياق.'
      },
      compression: {
        enabled: 'تلخيص السياق الأقدم عندما تكبر المحادثات.'
      },
      voice: {
        autoTts: 'نطق ردود المساعد تلقائيًا.'
      },
      tts: {
        xai: {
          voiceId: 'معرّف صوت xAI (مثل eve) أو معرّف صوت مخصص.',
          language: 'رمز اللغة المنطوقة، مثل en.'
        },
        neutts: {
          device: 'جهاز الاستدلال المحلي لـ NeuTTS.'
        }
      },
      stt: {
        enabled: 'تفعيل تفريغ الكلام المحلي أو المعتمد على مزوّد.',
        elevenlabs: {
          languageCode: 'رمز لغة اختياري بمعيار ISO-639-3. اتركه فارغًا ليكتشف ElevenLabs اللغة تلقائيًا.'
        }
      },
      updates: {
        nonInteractiveLocalChanges:
          'عندما يحدّث Simplicio نفسه من داخل التطبيق (دون طلب في الطرفية)، احتفظ بالتعديلات المحلية على المصدر (تخزين مؤقت) أو تجاهلها. تحديثات الطرفية تسأل دائمًا.'
      }
    }),
    about: {
      heading: 'Simplicio Desktop',
      version: value => `الإصدار ${value}`,
      versionUnavailable: 'الإصدار غير متاح',
      updates: 'التحديثات',
      checkNow: 'التحقق الآن',
      checking: 'جارٍ التحقق…',
      seeWhatsNew: 'عرض الجديد',
      updateNow: 'التحديث الآن',
      releaseNotes: 'ملاحظات الإصدار',
      onLatest: 'أنت على أحدث إصدار.',
      installing: 'يجري تثبيت تحديث حاليًا.',
      cantUpdate: 'لا يمكن لهذا الإصدار تحديث نفسه من داخل التطبيق.',
      cantReach: 'تعذّر الوصول إلى خادم التحديث.',
      tapCheck: 'اضغط "التحقق الآن" للبحث عن تحديثات.',
      updateReady: count =>
        arPlural(count, {
          one: 'تحديث جديد جاهز (يتضمن تغييرًا واحدًا).',
          two: 'تحديث جديد جاهز (يتضمن تغييرين).',
          few: `تحديث جديد جاهز (يتضمن ${count} تغييرات).`,
          many: `تحديث جديد جاهز (يتضمن ${count} تغييرًا).`,
          other: `تحديث جديد جاهز (يتضمن ${count} تغيير).`
        }),
      lastChecked: age => `آخر تحقق ${age}`,
      justNowSuffix: ' · الآن',
      automaticUpdates: 'التحديثات التلقائية',
      automaticUpdatesDesc: 'يتحقق Simplicio من التحديثات تلقائيًا في الخلفية ويعلمك عند جهوزية أحدها.',
      branchCommit: (branch, commit) => `الفرع ${branch} · Commit ${commit}`,
      never: 'أبدًا',
      justNow: 'الآن',
      minAgo: count =>
        arPlural(count, {
          one: 'منذ دقيقة واحدة',
          two: 'منذ دقيقتين',
          few: `منذ ${count} دقائق`,
          many: `منذ ${count} دقيقة`,
          other: `منذ ${count} دقيقة`
        }),
      hoursAgo: count =>
        arPlural(count, {
          one: 'منذ ساعة واحدة',
          two: 'منذ ساعتين',
          few: `منذ ${count} ساعات`,
          many: `منذ ${count} ساعة`,
          other: `منذ ${count} ساعة`
        }),
      daysAgo: count =>
        arPlural(count, {
          one: 'منذ يوم واحد',
          two: 'منذ يومين',
          few: `منذ ${count} أيام`,
          many: `منذ ${count} يومًا`,
          other: `منذ ${count} يوم`
        })
    },
    config: {
      none: 'بلا',
      noneParen: '(بلا)',
      notSet: 'غير محدد',
      commaSeparated: 'قيم مفصولة بفواصل',
      loading: 'جارٍ تحميل إعدادات Simplicio...',
      emptyTitle: 'لا شيء لضبطه',
      emptyDesc: 'لا يحتوي هذا القسم على إعدادات قابلة للتعديل.',
      failedLoad: 'فشل تحميل الإعدادات',
      autosaveFailed: 'فشل الحفظ التلقائي',
      imported: 'تم استيراد الإعدادات',
      invalidJson: 'صيغة JSON غير صالحة للإعدادات'
    },
    credentials: {
      pasteKey: 'لصق المفتاح',
      pasteLabelKey: label => `لصق مفتاح ${label}`,
      optional: 'اختياري',
      enterValueFirst: 'أدخل قيمة أولًا.',
      couldNotSave: 'تعذّر حفظ بيانات الاعتماد.',
      remove: 'إزالة',
      or: 'أو',
      escToCancel: 'Esc للإلغاء',
      getKey: 'الحصول على مفتاح',
      saving: 'جارٍ الحفظ'
    },
    envActions: {
      actionsFor: label => `إجراءات لـ${label}`,
      credentialActions: 'إجراءات بيانات الاعتماد',
      docs: 'الوثائق',
      hideValue: 'إخفاء القيمة',
      revealValue: 'إظهار القيمة',
      replace: 'استبدال',
      set: 'تعيين',
      clear: 'مسح'
    },
    gateway: {
      loading: 'جارٍ تحميل إعدادات البوابة...',
      unavailableTitle: 'إعدادات البوابة غير متاحة',
      unavailableDesc: 'جسر IPC الخاص بسطح المكتب لا يوفر إعدادات البوابة.',
      title: 'اتصال البوابة',
      envOverride: 'تجاوز بيئي',
      intro:
        'يشغّل Simplicio Desktop بوابته المحلية الخاصة افتراضيًا. استخدم بوابة بعيدة عندما تريد أن يتحكم هذا التطبيق في خادم Simplicio خلفي يعمل بالفعل على جهاز آخر أو خلف وكيل موثوق. اختر ملفًا شخصيًا أدناه لمنحه مضيفًا بعيدًا خاصًا به.',
      appliesTo: 'ينطبق على',
      allProfiles: 'كل الملفات الشخصية',
      defaultConnection: 'الاتصال الافتراضي لكل ملف شخصي ليس له تجاوز خاص به.',
      profileConnection: profile =>
        `يُستخدم الاتصال فقط عندما يكون "${profile}" هو الملف الشخصي النشط. اضبطه على محلي لوراثة الافتراضي.`,
      envOverrideTitle: 'متغيرات البيئة تتحكم في جلسة سطح المكتب هذه.',
      envOverrideDesc: 'ألغِ ضبط HERMES_DESKTOP_REMOTE_URL وHERMES_DESKTOP_REMOTE_TOKEN لاستخدام الإعداد المحفوظ أدناه.',
      localTitle: 'البوابة المحلية',
      localDesc: 'ابدأ خادم Simplicio خاصًا على localhost. هذا هو الافتراضي ويعمل دون اتصال.',
      remoteTitle: 'البوابة البعيدة',
      remoteDesc:
        'اربط غلاف سطح المكتب هذا بخادم Simplicio بعيد. تستخدم البوابات المستضافة OAuth أو اسم مستخدم وكلمة مرور؛ وقد تستخدم البوابات ذاتية الاستضافة رمز جلسة.',
      remoteUrlTitle: 'العنوان البعيد',
      remoteUrlDesc: 'العنوان الأساسي لخادم لوحة التحكم البعيد. بادئات المسار مدعومة، مثل /hermes.',
      probing: 'جارٍ التحقق من طريقة مصادقة هذه البوابة…',
      probeError: 'تعذّر الوصول إلى هذه البوابة بعد. تحقق من العنوان — ستظهر طريقة المصادقة عند استجابتها.',
      signedIn: 'تم تسجيل الدخول',
      signIn: 'تسجيل الدخول',
      signOut: 'تسجيل الخروج',
      signInWith: provider => `تسجيل الدخول باستخدام ${provider}`,
      authTitle: 'المصادقة',
      authSignedInPassword: 'تستخدم هذه البوابة اسم مستخدم وكلمة مرور. أنت مسجَّل الدخول؛ تتجدد الجلسة تلقائيًا.',
      authSignedInOauth: 'تستخدم هذه البوابة OAuth. أنت مسجَّل الدخول؛ تتجدد الجلسة تلقائيًا.',
      authNeedsPassword: 'تستخدم هذه البوابة اسم مستخدم وكلمة مرور. سجّل الدخول لتفويض تطبيق سطح المكتب هذا.',
      authNeedsOauth: provider => `تستخدم هذه البوابة OAuth. سجّل الدخول باستخدام ${provider} لتفويض تطبيق سطح المكتب هذا.`,
      tokenTitle: 'رمز الجلسة',
      tokenDesc: 'رمز جلسة لوحة التحكم المستخدم للوصول عبر REST وWebSocket. اتركه فارغًا للاحتفاظ بالرمز المحفوظ.',
      existingToken: value => `الرمز الحالي ${value}`,
      savedToken: 'محفوظ',
      pasteSessionToken: 'لصق رمز الجلسة',
      testRemote: 'اختبار البعيد',
      saveForRestart: 'حفظ لإعادة التشغيل القادمة',
      saveAndReconnect: 'حفظ وإعادة الاتصال',
      diagnostics: 'التشخيص',
      diagnosticsDesc: 'إظهار desktop.log في مدير الملفات — مفيد عند فشل بدء تشغيل البوابة.',
      openLogs: 'فتح السجلات',
      incompleteTitle: 'البوابة البعيدة غير مكتملة',
      incompleteSignIn: 'أدخل عنوانًا بعيدًا وسجّل الدخول قبل التبديل إلى البعيد.',
      incompleteToken: 'أدخل عنوانًا بعيدًا ورمز جلسة قبل التبديل إلى البعيد.',
      incompleteSignInTest: 'أدخل عنوانًا بعيدًا وسجّل الدخول قبل الاختبار.',
      incompleteTokenTest: 'أدخل عنوانًا بعيدًا ورمز جلسة قبل الاختبار.',
      enterUrlFirst: 'أدخل عنوانًا بعيدًا أولًا.',
      restartingTitle: 'إعادة تشغيل اتصال البوابة',
      savedTitle: 'تم حفظ إعدادات البوابة',
      restartingMessage: 'سيعيد Simplicio Desktop الاتصال باستخدام الإعدادات المحفوظة.',
      savedMessage: 'تم الحفظ لإعادة التشغيل القادمة.',
      connectedTo: (baseUrl, version) => `متصل بـ ${baseUrl}${version ? ` · Simplicio ${version}` : ''}`,
      reachableTitle: 'البوابة البعيدة قابلة للوصول',
      signedOutTitle: 'تم تسجيل الخروج',
      signedOutMessage: 'تم مسح جلسة البوابة البعيدة.',
      failedLoad: 'فشل تحميل إعدادات البوابة',
      signInFailed: 'فشل تسجيل الدخول',
      signOutFailed: 'فشل تسجيل الخروج',
      testFailed: 'فشل اختبار البوابة البعيدة',
      applyFailed: 'تعذّر تطبيق إعدادات البوابة',
      saveFailed: 'تعذّر حفظ إعدادات البوابة'
    },
    keys: {
      loading: 'جارٍ تحميل مفاتيح API وبيانات الاعتماد...',
      failedLoad: 'فشل تحميل مفاتيح API',
      empty: 'لا شيء مضبوط في هذه الفئة بعد.'
    },
    mcp: {
      loading: 'جارٍ تحميل خوادم MCP...',
      failedLoad: 'فشل تحميل إعدادات MCP',
      nameRequiredTitle: 'الاسم مطلوب',
      nameRequiredMessage: 'أعطِ خادم MCP هذا مفتاح إعداد.',
      objectRequired: 'يجب أن يكون إعداد الخادم كائن JSON',
      invalidJson: 'صيغة JSON غير صالحة لـ MCP',
      saveFailed: 'فشل الحفظ',
      removeFailed: 'فشلت الإزالة',
      gatewayUnavailableTitle: 'البوابة غير متاحة',
      gatewayUnavailableMessage: 'أعد الاتصال بالبوابة قبل إعادة تحميل MCP.',
      reloadedTitle: 'أُعيد تحميل أدوات MCP',
      reloadedMessage: 'تُطبَّق مخططات الأدوات الجديدة على الجولات القادمة.',
      reloadFailed: 'فشلت إعادة تحميل MCP',
      savedTitle: 'تم حفظ خادم MCP',
      savedMessage: name => `يُطبَّق ${name} بعد إعادة تحميل MCP.`,
      newServer: 'خادم جديد',
      reload: 'إعادة تحميل MCP',
      reloading: 'جارٍ إعادة التحميل...',
      emptyTitle: 'لا توجد خوادم MCP',
      emptyDesc: 'أضف خادم stdio أو HTTP لإتاحة أدوات MCP.',
      disabled: 'معطَّل',
      editServer: 'تعديل الخادم',
      name: 'الاسم',
      serverJson: 'JSON الخادم',
      remove: 'إزالة',
      saveServer: 'حفظ الخادم'
    },
    model: {
      loading: 'جارٍ تحميل إعداد النموذج...',
      appliesDesc: 'ينطبق على الجلسات الجديدة. استخدم مُنتقي النماذج في مربع الكتابة لتبديل المحادثة النشطة فورًا.',
      provider: 'المزوّد',
      model: 'النموذج',
      applying: 'جارٍ التطبيق...',
      defaultsLabel: 'الإعدادات الافتراضية',
      reasoning: 'التفكير',
      reasoningOff: 'إيقاف',
      defaultsFailed: 'فشل حفظ إعدادات النموذج الافتراضية',
      auxiliaryTitle: 'النماذج المساعدة',
      resetAllToMain: 'إعادة ضبط الكل إلى الرئيسي',
      auxiliaryDesc: 'تعمل المهام المساعدة على النموذج الرئيسي افتراضيًا. خصّص نموذجًا مخصصًا لأي مهمة لتجاوز ذلك.',
      setToMain: 'تعيين إلى الرئيسي',
      change: 'تغيير',
      autoUseMain: 'تلقائي · استخدام النموذج الرئيسي',
      providerDefault: '(افتراضي المزوّد)',
      tasks: {
        vision: { label: 'الرؤية', hint: 'تحليل الصور' },
        web_extract: { label: 'استخراج الويب', hint: 'تلخيص الصفحة' },
        compression: { label: 'الضغط', hint: 'ضغط السياق' },
        skills_hub: { label: 'مركز المهارات', hint: 'البحث عن المهارات' },
        approval: { label: 'الموافقة', hint: 'الموافقة التلقائية الذكية' },
        mcp: { label: 'MCP', hint: 'توجيه أدوات MCP' },
        title_generation: { label: 'توليد العناوين', hint: 'عناوين الجلسات' },
        curator: { label: 'المنسّق', hint: 'مراجعة استخدام المهارات' }
      }
    },
    providers: {
      connectAccount: 'ربط حساب',
      haveApiKey: 'لديك مفتاح API بدلًا من ذلك؟',
      intro:
        'سجّل الدخول باستخدام اشتراك — بلا مفتاح API لنسخه. يشغّل Simplicio تسجيل الدخول عبر المتصفح نيابة عنك، هنا في التطبيق مباشرة.',
      connected: 'متصل',
      collapse: 'طي',
      connectAnother: 'ربط مزوّد آخر',
      otherProviders: 'مزوّدون آخرون',
      disconnect: 'قطع الاتصال',
      disconnectInTerminal: 'قطع الاتصال (يشغّل أمر الإزالة في الطرفية)',
      removeConfirm: provider => `إزالة ${provider}؟`,
      removeExternalGeneric: provider => `تتم إدارة ${provider} عبر أداة سطر أوامره الخاصة — أزله من هناك.`,
      removeKeyManaged: provider => `${provider} مضبوط من مفتاح API. أزله من مفاتيح API.`,
      removeTerminalConfirm: (provider, command) =>
        `قطع الاتصال بـ${provider}؟ سيشغّل هذا "${command}" في الطرفية لمسح بيانات الاعتماد.`,
      removeTerminalRunning: provider => `جارٍ تشغيل قطع اتصال ${provider} في الطرفية…`,
      removedTitle: 'أُزيل الحساب',
      removedMessage: provider => `أُزيل ${provider}.`,
      failedRemove: provider => `تعذّر إزالة ${provider}`,
      noProviderKeys: 'لا تتوفر مفاتيح API لمزوّدين.',
      searchKeys: 'ابحث عن مزوّدين…',
      noKeysMatch: 'لا يوجد مزوّدون مطابقون لبحثك.',
      loading: 'جارٍ تحميل المزوّدين...'
    },
    sessions: {
      loading: 'جارٍ تحميل الجلسات المؤرشفة…',
      archivedTitle: 'الجلسات المؤرشفة',
      archivedIntro:
        'المحادثات المؤرشفة مخفية عن الشريط الجانبي لكنها تحتفظ بكل رسائلها. اضغط Ctrl/⌘ مع النقر على محادثة في الشريط الجانبي لأرشفتها.',
      emptyArchivedTitle: 'لا شيء مؤرشف',
      emptyArchivedDesc: 'أرشف محادثة لإخفائها هنا.',
      unarchive: 'إلغاء الأرشفة',
      deletePermanently: 'حذف نهائي',
      messages: count =>
        arPlural(count, {
          one: 'رسالة واحدة',
          two: 'رسالتان',
          few: `${count} رسائل`,
          many: `${count} رسالة`,
          other: `${count} رسالة`
        }),
      restored: 'تمت الاستعادة',
      deleteConfirm: title => `حذف "${title}" نهائيًا؟ لا يمكن التراجع عن هذا.`,
      defaultDirTitle: 'مجلد المشروع الافتراضي',
      defaultDirDesc: 'تبدأ الجلسات الجديدة في هذا المجلد ما لم تختر آخر. اتركه غير محدد لاستخدام مجلدك الرئيسي.',
      defaultDirUpdated: 'تحديث مجلد المشروع الافتراضي — ابدأ محادثة جديدة (Ctrl/⌘+N) ليصبح ساري المفعول',
      defaultsTo: label => `الافتراضي هو ${label}.`,
      change: 'تغيير',
      choose: 'اختيار',
      clear: 'مسح',
      notSet: 'غير محدد',
      failedLoad: 'تعذّر تحميل الجلسات المؤرشفة',
      unarchiveFailed: 'فشل إلغاء الأرشفة',
      deleteFailed: 'فشل الحذف',
      updateDirFailed: 'تعذّر تحديث المجلد الافتراضي',
      clearDirFailed: 'تعذّر مسح المجلد الافتراضي'
    },
    toolsets: {
      loadingConfig: 'جارٍ تحميل الإعداد',
      savedTitle: 'تم حفظ بيانات الاعتماد',
      savedMessage: key => `تم تحديث ${key}.`,
      removedTitle: 'أُزيلت بيانات الاعتماد',
      removedMessage: key => `أُزيل ${key}.`,
      failedSave: key => `فشل حفظ ${key}`,
      failedRemove: key => `فشلت إزالة ${key}`,
      failedReveal: key => `فشل إظهار ${key}`,
      removeConfirm: key => `إزالة ${key} من .env؟`,
      set: 'تعيين',
      notSet: 'غير محدد',
      selectedTitle: 'تم اختيار المزوّد',
      selectedMessage: provider => `${provider} نشط الآن.`,
      failedSelect: provider => `فشل اختيار ${provider}`,
      failedLoad: 'فشل تحميل إعداد الأدوات',
      noProviderOptions: 'لا تتوفر خيارات مزوّدين لمجموعة الأدوات هذه — فعّلها وستعمل مع إعدادك الحالي.',
      noProviders: 'لا يتوفر مزوّدون لمجموعة الأدوات هذه حاليًا.',
      ready: 'جاهز',
      nousIncluded: 'مُدرَج مع اشتراك Nous — سجّل الدخول إلى Nous Portal لتفعيله.',
      noApiKeyRequired: 'لا حاجة إلى مفتاح API.',
      postSetupHint: step => `يحتاج هذا الخادم الخلفي إلى تثبيت لمرة واحدة (${step}). يعمل على هذا الجهاز — قد يستغرق بضع دقائق.`,
      postSetupRun: 'تشغيل الإعداد',
      postSetupRunning: 'جارٍ التثبيت…',
      postSetupStarting: 'جارٍ البدء…',
      postSetupCompleteTitle: 'اكتمل الإعداد',
      postSetupCompleteMessage: step => `تم تثبيت ${step}.`,
      postSetupErrorTitle: 'انتهى الإعداد بأخطاء',
      postSetupErrorMessage: step => `تحقق من سجل ${step}.`,
      postSetupFailed: step => `فشل تشغيل إعداد ${step}`
    }
  },

  skills: {
    tabSkills: 'المهارات',
    tabToolsets: 'مجموعات الأدوات',
    all: 'الكل',
    searchSkills: 'البحث في المهارات...',
    searchToolsets: 'البحث في مجموعات الأدوات...',
    refresh: 'تحديث المهارات',
    refreshing: 'جارٍ تحديث المهارات',
    loading: 'جارٍ تحميل الإمكانيات...',
    noSkillsTitle: 'لم يُعثر على مهارات',
    noSkillsDesc: 'جرّب بحثًا أوسع أو فئة مختلفة.',
    noToolsetsTitle: 'لم يُعثر على مجموعات أدوات',
    noToolsetsDesc: 'جرّب استعلام بحث أوسع.',
    noDescription: 'لا يوجد وصف.',
    configured: 'مضبوطة',
    needsKeys: 'يحتاج مفاتيح',
    toolsetsEnabled: (enabled, total) => `${enabled}/${total} مجموعات أدوات مفعّلة`,
    configureToolset: label => `ضبط ${label}`,
    toggleToolset: label => `تبديل مجموعة أدوات ${label}`,
    skillsLoadFailed: 'فشل تحميل المهارات',
    toolsetsRefreshFailed: 'فشل تحديث مجموعات الأدوات',
    skillEnabled: 'تم تفعيل المهارة',
    skillDisabled: 'تم تعطيل المهارة',
    toolsetEnabled: 'تم تفعيل مجموعة الأدوات',
    toolsetDisabled: 'تم تعطيل مجموعة الأدوات',
    appliesToNewSessions: name => `يُطبَّق ${name} على الجلسات الجديدة.`,
    failedToUpdate: name => `فشل تحديث ${name}`
  },

  starmap: {
    title: 'خريطة الذاكرة',
    subtitle: (nodes, clusters) =>
      `${arPlural(nodes, { one: 'مهارة واحدة', two: 'مهارتان', few: `${nodes} مهارات`, many: `${nodes} مهارة`, other: `${nodes} مهارة` })} عبر ${arPlural(clusters, { one: 'فئة واحدة', two: 'فئتان', few: `${clusters} فئات`, many: `${clusters} فئة`, other: `${clusters} فئة` })}`,
    close: 'إغلاق خريطة الذاكرة',
    refresh: 'تحديث',
    memory: 'الذاكرة',
    filterAll: 'الكل',
    filterUsed: 'المستخدَمة',
    filterLearned: 'المكتسَبة',
    viewGraph: 'الرسم البياني',
    loadFailed: 'تعذّر تحميل خريطة الذاكرة',
    loading: 'جارٍ التحميل…',
    emptyTitle: 'لم يُكتسب شيء بعد',
    emptyDesc: 'مع بناء Simplicio للمهارات والذكريات الخاصة بعملك، ستظهر هنا.',
    share: 'مشاركة الخريطة',
    shareHint:
      'انسخ الرمز لمشاركة هذه الخريطة، أو الصق رمزًا لتحميله. يتضمن التخطيط فقط، وليس نص ذاكرتك أو مهاراتك.',
    shareTitle: 'استيراد / تصدير الخريطة',
    sharePlaceholder: 'الصق رمز خريطة…',
    copy: 'نسخ رمز الخريطة',
    copied: 'تم النسخ!',
    importMap: 'استيراد خريطة',
    importBtn: 'تحميل',
    importEmpty: 'الصق رمز خريطة لتحميلها.',
    importSuccess: nodes =>
      arPlural(nodes, {
        one: 'تم تحميل خريطة بعقدة واحدة.',
        two: 'تم تحميل خريطة بعقدتين.',
        few: `تم تحميل خريطة بـ${nodes} عقد.`,
        many: `تم تحميل خريطة بـ${nodes} عقدة.`,
        other: `تم تحميل خريطة بـ${nodes} عقدة.`
      }),
    importedBadge: 'خريطة مستوردة',
    resetToMine: 'العودة إلى خريطتي'
  },
  agents: {
    close: 'إغلاق الوكلاء',
    title: 'شجرة التفريع',
    subtitle: 'نشاط الوكلاء الفرعيين المباشر للجولة الحالية.',
    emptyTitle: 'لا وكلاء فرعيون نشطون',
    emptyDesc: 'عندما تُفوِّض جولة عملًا، تُعرض هنا مستجدات الوكلاء الفرعيين.',
    running: 'قيد التشغيل',
    failed: 'فشل',
    done: 'تم',
    streaming: 'بث مباشر',
    files: 'الملفات',
    moreFiles: count =>
      arPlural(count, {
        one: '+ملف واحد إضافي',
        two: '+ملفان إضافيان',
        few: `+${count} ملفات إضافية`,
        many: `+${count} ملفًا إضافيًا`,
        other: `+${count} ملف إضافي`
      }),
    delegation: index => `التفويض ${index}`,
    workers: count =>
      arPlural(count, { one: 'عامل واحد', two: 'عاملان', few: `${count} عمّال`, many: `${count} عاملًا`, other: `${count} عامل` }),
    workersActive: count =>
      arPlural(count, { one: 'نشط واحد', two: 'نشطان', few: `${count} نشطة`, many: `${count} نشطًا`, other: `${count} نشط` }),
    agentsCount: count =>
      arPlural(count, { one: 'وكيل واحد', two: 'وكيلان', few: `${count} وكلاء`, many: `${count} وكيلًا`, other: `${count} وكيل` }),
    activeCount: count =>
      arPlural(count, { one: 'نشط واحد', two: 'نشطان', few: `${count} نشطة`, many: `${count} نشطًا`, other: `${count} نشط` }),
    failedCount: count =>
      arPlural(count, {
        one: 'فشل واحد',
        two: 'فشلان',
        few: `${count} حالات فشل`,
        many: `${count} فشلًا`,
        other: `${count} فشل`
      }),
    toolsCount: count =>
      arPlural(count, { one: 'أداة واحدة', two: 'أداتان', few: `${count} أدوات`, many: `${count} أداة`, other: `${count} أداة` }),
    filesCount: count =>
      arPlural(count, { one: 'ملف واحد', two: 'ملفان', few: `${count} ملفات`, many: `${count} ملفًا`, other: `${count} ملف` }),
    updatedAgo: age => `تحديث ${age}`,
    ageNow: 'الآن',
    ageSeconds: seconds =>
      arPlural(seconds, {
        one: 'منذ ثانية',
        two: 'منذ ثانيتين',
        few: `منذ ${seconds} ثوانٍ`,
        many: `منذ ${seconds} ثانية`,
        other: `منذ ${seconds} ثانية`
      }),
    ageMinutes: minutes =>
      arPlural(minutes, {
        one: 'منذ دقيقة',
        two: 'منذ دقيقتين',
        few: `منذ ${minutes} دقائق`,
        many: `منذ ${minutes} دقيقة`,
        other: `منذ ${minutes} دقيقة`
      }),
    ageHours: hours =>
      arPlural(hours, {
        one: 'منذ ساعة',
        two: 'منذ ساعتين',
        few: `منذ ${hours} ساعات`,
        many: `منذ ${hours} ساعة`,
        other: `منذ ${hours} ساعة`
      }),
    durationSeconds: seconds => `${seconds} ث`,
    durationMinutes: (minutes, seconds) => `${minutes} د ${seconds} ث`,
    tokensK: k => `${k} ألف رمز`,
    tokens: value =>
      arPlural(value, { one: 'رمز واحد', two: 'رمزان', few: `${value} رموز`, many: `${value} رمزًا`, other: `${value} رمز` })
  },

  savings: {
    title: 'اقتصاد الرموز',
    subtitle: 'وفورات رموز حقيقية موثّقة — مقاسة حيث أمكن، ومقدَّرة حيث لا يمكن.',
    close: 'إغلاق الوفورات',
    refresh: 'تحديث',
    refreshing: 'جارٍ التحديث…',
    lastUpdated: time => `تم التحديث ${time}`,
    heroTotalSavedLabel: 'إجمالي الرموز الموفَّرة',
    heroPctSavedLabel: 'نسبة التوفير',
    heroSpentLabel: 'المُنفَق هذه الفترة',
    heroSpentHint: baseline => `من أصل ${baseline} كخط أساس`,
    evidenceSectionTitle: 'الأدلة',
    evidenceSectionDesc: 'كل رقم أدناه مُوسَم بـ"مقاس" أو "مقدَّر" — ولا يُعرض أبدًا دون تصنيف.',
    measuredLabel: 'مقاس',
    measuredTooltip: 'استخدام حقيقي أبلغ عنه المزوّد أو دفتر الوفورات.',
    estimatedLabel: 'مقدَّر',
    estimatedTooltip: 'تقدير إرشادي، وليس رقمًا مُبلَّغًا عنه من المزوّد.',
    unknownProofLabel: 'غير موسوم',
    unknownProofTooltip: 'لا يحمل هذا السجل وسم نوع إثبات في التقرير.',
    chartTitle: 'الوفورات التراكمية بمرور الوقت',
    perSessionTitle: 'حسب الجلسة',
    perSessionAggregatedNote: 'لا يحتوي هذا التقرير على تفصيل لكل جلسة — يعرض أحداث الدفتر الخام بدلًا من ذلك.',
    noEventListDesc: 'يحتوي هذا التقرير على إجماليات مجمّعة فقط — لا توجد قائمة أحداث لعرضها.',
    columnTimestamp: 'الوقت',
    columnContext: 'الجلسة / المستودع / النموذج',
    columnSpent: 'المُنفَق',
    columnBaseline: 'خط الأساس',
    columnSaved: 'الموفَّر',
    columnProof: 'الإثبات',
    mcpUnknown: 'حالة MCP غير معروفة',
    mcpRunning: 'يعمل خادم MCP',
    mcpRunningPid: pid => `يعمل خادم MCP (pid ${pid})`,
    mcpStopped: 'توقف خادم MCP',
    mcpStoppedNoDetail: 'متوقف — لم يُبلَّغ عن خطأ',
    mcpRestarts: count =>
      arPlural(count, {
        one: 'إعادة تشغيل واحدة',
        two: 'إعادتا تشغيل',
        few: `${count} إعادات تشغيل`,
        many: `${count} إعادة تشغيل`,
        other: `${count} إعادة تشغيل`
      }),
    backendUnavailableTitle: 'خادم الوفورات الخلفي غير متاح',
    backendUnavailableDesc:
      'window.simplicioSavings غير مُتاح في هذا الإصدار. حدّث تطبيق سطح المكتب، أو شغّل `simplicio savings report --json` من طرفية للتحقق من الدفتر مباشرة.',
    errorTitle: 'تعذّر تحميل تقرير الوفورات',
    retry: 'إعادة المحاولة',
    emptyTitle: 'لم تُسجَّل أي وفورات بعد',
    emptyDesc: 'شغّل `simplicio savings record --spent <N> --baseline <N> --proof-kind estimated` لتسجيل أول إدخال لك.',
    loading: 'جارٍ تحميل بيانات الوفورات…',
    cockpit: {
      mcpLabel: 'خادم MCP',
      llmLabel: 'نموذج اللغة المحلي',
      neuralLabel: 'قاعدة البيانات العصبية',
      runtimeLabel: 'بيئة التشغيل',
      running: 'يعمل',
      stopped: 'متوقف',
      checking: 'جارٍ التحقق…',
      unavailable: 'غير متاح',
      bridgeMissing: 'غير متاح في هذا الإصدار.',
      startAction: 'تشغيل',
      stopAction: 'إيقاف',
      confirmStop: 'تأكيد الإيقاف؟',
      diagnostics: 'التشخيص',
      uptime: duration => `يعمل منذ ${duration}`,
      local: 'محلي',
      remote: 'بعيد',
      offlineFirst: 'دون اتصال أولًا',
      noModel: 'لا يوجد نموذج مضبوط',
      memories: count => `${count} ذكرى`,
      byModelTitle: 'الوفورات حسب النموذج',
      byProofTitle: 'الوفورات حسب نوع الإثبات',
      sessionsTitle: 'الجلسات',
      sessionsDesc: 'كل تشغيل كخط زمني قابل للتدقيق: الأوامر المستخدمة، والرموز، وسلسلة التجزئة القابلة للتحقق.',
      eventsCount: count =>
        arPlural(count, { one: 'حدث واحد', two: 'حدثان', few: `${count} أحداث`, many: `${count} حدثًا`, other: `${count} حدث` }),
      noEvents: 'لم تُسجَّل أي أحداث لهذا التشغيل.',
      savedShort: 'موفَّر',
      hashChainTooltip: 'سلسلة تجزئة قابلة للتحقق (HBP): السابق -> هذا',
      sourceLabel: 'المصدر:',
      skippedLines: count =>
        arPlural(count, {
          one: 'تم تخطي سطر واحد غير قابل للتحليل في الدفتر',
          two: 'تم تخطي سطرين غير قابلين للتحليل في الدفتر',
          few: `تم تخطي ${count} أسطر غير قابلة للتحليل في الدفتر`,
          many: `تم تخطي ${count} سطرًا غير قابل للتحليل في الدفتر`,
          other: `تم تخطي ${count} سطر غير قابل للتحليل في الدفتر`
        }),
      superSavingsAria: 'وفورات تتجاوز 90 بالمئة'
    },
    live: {
      title: 'النشاط المباشر',
      subtitle: 'بث مباشر من لوحة تحكم بيئة التشغيل — كل تشغيل، أمرًا بأمر.',
      badgeLive: 'مباشر',
      badgeStatic: 'نشط',
      updatedNow: 'تم التحديث الآن',
      updatedAgo: time => `تم التحديث منذ ${time}`,
      eventsLabel: 'الأحداث',
      savedLabel: 'الموفَّر',
      savedPctLabel: 'نسبة التوفير',
      costSavedLabel: 'التكلفة الموفَّرة',
      timeseriesTitle: 'النشاط بمرور الوقت',
      byProviderTitle: 'حسب المزوّد',
      byRepoTitle: 'حسب المستودع',
      recentTitle: 'الأحدث',
      recentEmpty: 'لم يُسجَّل أي نشاط بعد.',
      recentSpentToSaved: (spent, saved) => `${spent} → ${saved} موفَّر`,
      unavailableTitle: 'لوحة التحكم المباشرة غير متاحة',
      unavailableDesc:
        'لا يوفر هذا الإصدار جسر لوحة التحكم المباشرة بعد. حدّث تطبيق سطح المكتب لرؤية النشاط الفوري هنا.',
      startingTitle: 'جارٍ تشغيل لوحة التحكم المباشرة…',
      startingDesc: 'جارٍ تشغيل `simplicio dashboard` — يستغرق هذا لحظة فقط.',
      errorTitle: 'تعذّر الوصول إلى لوحة التحكم المباشرة',
      retry: 'إعادة المحاولة',
      retrying: 'جارٍ المحاولة…',
      emptyTitle: 'لا يوجد نشاط مباشر بعد',
      emptyDesc: 'شغّل مهمة مدعومة بـSimplicio وستظهر هنا خلال ثوانٍ.'
    }
  },

  computerUse: {
    title: 'التحكم في الحاسوب',
    pauseAction: 'إيقاف التحكم في الحاسوب مؤقتًا',
    resumeAction: 'استئناف التحكم في الحاسوب',
    pausedStatus: 'متوقف مؤقتًا',
    activeStatus: 'نشط',
    pausedHint: 'لن يتحكم الوكيل بفأرتك أو لوحة مفاتيحك.',
    activeHint: 'يمكن للوكيل التحكم بفأرتك ولوحة مفاتيحك تلقائيًا.',
    pausedToast: 'أُوقِف التحكم في الحاسوب مؤقتًا',
    resumedToast: 'استؤنف التحكم في الحاسوب — يمكن للوكيل التصرف تلقائيًا',
    toggleFailed: 'تعذّر تحديث حالة التحكم في الحاسوب',
    statusLoadFailed: 'تعذّر قراءة حالة التحكم في الحاسوب'
  },

  commandCenter: {
    close: 'إغلاق مركز الأوامر',
    paletteTitle: 'لوحة الأوامر',
    back: 'رجوع',
    searchPlaceholder: 'البحث في الجلسات والعروض والإجراءات',
    goTo: 'الانتقال إلى',
    goToSession: 'الانتقال إلى الجلسة',
    branches: 'الفروع',
    startInBranch: branch => `محادثة جديدة في ${branch}`,
    commandCenter: 'مركز الأوامر',
    appearance: 'المظهر',
    settings: 'الإعدادات',
    changeTheme: 'تغيير السمة',
    changeColorMode: 'تغيير وضع الألوان...',
    pets: {
      title: 'الحيوانات الأليفة',
      placeholder: 'ابحث عن حيوانات أليفة…',
      loading: 'جارٍ تحميل معرض petdex…',
      error: 'تعذّر الوصول إلى معرض petdex.',
      staleBackend: 'أعد تشغيل Simplicio لاستخدام الحيوانات الأليفة — الخادم الخلفي أقدم من هذه الميزة.',
      empty: 'لا توجد حيوانات أليفة مطابقة.',
      turnOff: 'إيقاف',
      turnOn: 'تشغيل',
      installed: 'مثبَّت',
      generatedTag: 'مُولَّد',
      adoptFailed: 'تعذّر تبنّي ذلك الحيوان الأليف.',
      toggleFailed: 'تعذّر تبديل حالة الحيوان الأليف.',
      noneAvailable: 'لا تتوفر حيوانات أليفة — اختر واحدًا أدناه لتثبيته.'
    },
    generatePet: {
      title: 'توليد حيوان أليف',
      placeholder: 'صف حيوانًا أليفًا لتوليده…',
      promptHint: 'اكتب وصفًا، ثم اضغط Enter لرسم أربعة أشكال.',
      readyHint: 'اضغط Enter لرسم أربعة أشكال من وصفك.',
      generate: 'توليد',
      generating: 'جارٍ التوليد…',
      retry: 'إعادة المحاولة',
      hatch: 'فقس',
      spawning: 'جارٍ الإنشاء…',
      hatching: 'جارٍ تفقيس حيوانك الأليف…',
      hatchingSub: 'جارٍ بث الحياة فيه…',
      hatched: 'لقد فقس!',
      hatchRow: (_state, done, total) => `جارٍ رسم الإطار ${done} من ${total}…`,
      hatchComposing: 'جارٍ تجميعه…',
      hatchSaving: 'أوشكنا على الانتهاء…',
      namePlaceholder: 'سمِّ حيوانك الأليف',
      staleBackend: 'حدّث Simplicio لتوليد حيوانات أليفة.',
      backgroundHint: 'يمكنك إغلاق هذا — سيعلمك Simplicio عند الانتهاء.',
      slowProviderHint: 'قد يستغرق هذا عدة دقائق',
      remix: 'إعادة مزج',
      remixConfirmTitle: 'إعادة مزج هذا الشكل؟',
      remixConfirmBody:
        'يولّد هذا مجموعة جديدة من المسودات باستخدام هذا الشكل كنقطة انطلاق. قد يستغرق عدة دقائق.',
      genericError: 'فشل التوليد — أعد المحاولة أو اختر اقتراحًا.',
      referenceImageTooLarge: 'صورة المرجع كبيرة جدًا. استخدم صورة أقل من 16 ميغابايت.',
      referenceImageInvalid: 'تعذّر قراءة صورة المرجع تلك. جرّب PNG أو JPG أو WebP أو GIF.',
      adopt: 'تبنّي',
      startOver: 'البدء من جديد'
    },
    installTheme: {
      title: 'تثبيت سمة...',
      placeholder: 'البحث في متجر VS Code...',
      loading: 'جارٍ البحث في المتجر...',
      error: 'تعذّر الوصول إلى المتجر.',
      empty: 'لا توجد سمات مطابقة.',
      install: 'تثبيت',
      installing: 'جارٍ التثبيت...',
      installed: 'مثبَّت',
      installs: count => `${count} عملية تثبيت`
    },
    settingsFields: 'حقول الإعدادات',
    mcpServers: 'خوادم MCP',
    archivedChats: 'المحادثات المؤرشفة',
    sections: { sessions: 'الجلسات', system: 'النظام', usage: 'الاستخدام' },
    sectionDescriptions: {
      sessions: 'البحث في الجلسات وإدارتها',
      system: 'الحالة والسجلات وإجراءات النظام',
      usage: 'الرموز والتكلفة ونشاط المهارات بمرور الوقت'
    },
    nav: {
      newChat: { title: 'جلسة جديدة', detail: 'ابدأ جلسة جديدة' },
      settings: { title: 'الإعدادات', detail: 'ضبط تطبيق Simplicio Agent لسطح المكتب' },
      skills: { title: 'الإمكانيات', detail: 'تفعيل المهارات ومجموعات الأدوات والمزوّدين' },
      messaging: { title: 'المراسلة', detail: 'إعداد Telegram وSlack وDiscord والمزيد' },
      artifacts: { title: 'المخرجات', detail: 'تصفح المخرجات المُولَّدة' }
    },
    sectionEntries: {
      sessions: { title: 'لوحة الجلسات', detail: 'البحث في الجلسات وتثبيتها وإدارتها' },
      system: { title: 'لوحة النظام', detail: 'حالة البوابة، السجلات، إعادة التشغيل/التحديث' },
      usage: { title: 'لوحة الاستخدام', detail: 'الرموز والتكلفة ونشاط المهارات' }
    },
    providerNavigate: 'التنقل',
    providerSessions: 'الجلسات',
    refresh: 'تحديث',
    refreshing: 'جارٍ التحديث...',
    noResults: 'لم يُعثر على نتائج مطابقة.',
    pinSession: 'تثبيت الجلسة',
    unpinSession: 'إلغاء تثبيت الجلسة',
    exportSession: 'تصدير الجلسة',
    deleteSession: 'حذف الجلسة',
    noSessions: 'لا توجد جلسات بعد.',
    gatewayRunning: 'بوابة المراسلة تعمل',
    gatewayStopped: 'توقفت بوابة المراسلة',
    hermesActiveSessions: (version, count) => `Simplicio ${version} · الجلسات النشطة ${count}`,
    restartGateway: 'إعادة تشغيل البوابة',
    gatewayRestartFailed: 'فشلت إعادة تشغيل البوابة.',
    updateHermes: 'تحديث Simplicio',
    actionRunning: 'قيد التشغيل',
    actionDone: 'تم',
    actionFailed: 'فشل',
    actionStartedWaiting: 'بدأ الإجراء، بانتظار الحالة...',
    loadingStatus: 'جارٍ تحميل الحالة...',
    recentLogs: 'السجلات الأخيرة',
    noLogs: 'لم تُحمَّل أي سجلات بعد.',
    days: count => `${count} يوم`,
    statSessions: 'الجلسات',
    statApiCalls: 'استدعاءات API',
    statTokens: 'الرموز داخل/خارج',
    statCost: 'التكلفة التقديرية',
    actualCost: cost => `الفعلية ${cost}`,
    loadingUsage: 'جارٍ تحميل الاستخدام...',
    noUsage: period => `لا يوجد استخدام في آخر ${period} يومًا.`,
    retry: 'إعادة المحاولة',
    dailyTokens: 'الرموز اليومية',
    input: 'الإدخال',
    output: 'الإخراج',
    noDailyActivity: 'لا يوجد نشاط يومي.',
    topModels: 'أفضل النماذج',
    noModelUsage: 'لا يوجد استخدام للنماذج بعد.',
    topSkills: 'أفضل المهارات',
    noSkillActivity: 'لا يوجد نشاط مهارات بعد.',
    actions: count => `${count} إجراء`
  },

  messaging: {
    search: 'البحث في المراسلة...',
    loading: 'جارٍ تحميل منصات المراسلة...',
    loadFailed: 'فشل تحميل منصات المراسلة',
    states: {
      connected: 'متصل',
      connecting: 'جارٍ الاتصال',
      disabled: 'معطَّل',
      fatal: 'خطأ',
      gateway_stopped: 'توقفت بوابة المراسلة',
      not_configured: 'يحتاج إعداد',
      pending_restart: 'يحتاج إعادة تشغيل',
      retrying: 'جارٍ إعادة المحاولة',
      startup_failed: 'فشل بدء التشغيل'
    },
    unknown: 'غير معروف',
    hintPendingRestart: 'أعد تشغيل البوابة من شريط الحالة لتطبيق هذا التغيير.',
    hintGatewayStopped: 'شغّل البوابة من شريط الحالة للاتصال.',
    credentialsSet: 'تم ضبط بيانات الاعتماد',
    needsSetup: 'يحتاج إعداد',
    gatewayStopped: 'توقفت بوابة المراسلة',
    getCredentials: 'الحصول على بيانات اعتمادك',
    openSetupGuide: 'فتح دليل الإعداد',
    required: 'مطلوب',
    recommended: 'موصى به',
    advanced: count => `متقدم (${count})`,
    noTokenNeeded: 'لا تحتاج هذه المنصة إلى رمز هنا. استخدم دليل الإعداد أعلاه، ثم فعّلها أدناه.',
    enabled: 'مفعَّل',
    disabled: 'معطَّل',
    unsavedChanges: 'تغييرات غير محفوظة',
    saving: 'جارٍ الحفظ...',
    saveChanges: 'حفظ التغييرات',
    saved: 'تم الحفظ',
    replaceValue: 'استبدال القيمة الحالية',
    openDocs: 'فتح الوثائق',
    clearField: key => `مسح ${key}`,
    enableAria: name => `تفعيل ${name}`,
    disableAria: name => `تعطيل ${name}`,
    platformEnabled: name => `تم تفعيل ${name}`,
    platformDisabled: name => `تم تعطيل ${name}`,
    restartToApply: 'يسري هذا التغيير بعد إعادة تشغيل البوابة.',
    setupSaved: name => `تم حفظ إعداد ${name}`,
    restartToReconnect: 'تسري بيانات الاعتماد الجديدة بعد إعادة تشغيل البوابة.',
    keyCleared: key => `تم مسح ${key}`,
    setupUpdated: name => `تم تحديث إعداد ${name}.`,
    failedUpdate: name => `فشل تحديث ${name}`,
    failedSave: name => `فشل حفظ ${name}`,
    failedClear: key => `فشل مسح ${key}`,
    fieldCopy: {
      TELEGRAM_BOT_TOKEN: {
        label: 'رمز البوت',
        help: 'أنشئ بوتًا عبر @BotFather، ثم الصق الرمز الذي يمنحك إياه.',
        placeholder: 'الصق رمز بوت Telegram'
      },
      TELEGRAM_ALLOWED_USERS: {
        label: 'معرّفات مستخدمي Telegram المسموح بهم',
        help: 'موصى به. معرّفات رقمية مفصولة بفواصل من @userinfobot. بدون هذا، يمكن لأي شخص مراسلة بوتك مباشرة.'
      },
      TELEGRAM_PROXY: { label: 'عنوان الوكيل (Proxy)', help: 'مطلوب فقط على الشبكات التي يُحظر فيها Telegram.' },
      DISCORD_BOT_TOKEN: {
        label: 'رمز البوت',
        help: 'أنشئ تطبيقًا في Discord Developer Portal، وأضف بوتًا، ثم الصق رمزه.'
      },
      DISCORD_ALLOWED_USERS: {
        label: 'معرّفات مستخدمي Discord المسموح بهم',
        help: 'موصى به. معرّفات مستخدمي Discord مفصولة بفواصل.'
      },
      DISCORD_REPLY_TO_MODE: { label: 'نمط الرد', help: 'first أو all أو off.' },
      DISCORD_ALLOW_ALL_USERS: {
        label: 'السماح لكل مستخدمي Discord',
        help: 'للتطوير فقط. عند التفعيل، يمكن لأي شخص مراسلة البوت دون قائمة سماح.'
      },
      DISCORD_HOME_CHANNEL: {
        label: 'معرّف القناة الرئيسية',
        help: 'القناة التي يرسل إليها البوت رسائل استباقية (مخرجات المهام المجدولة، التذكيرات).'
      },
      DISCORD_HOME_CHANNEL_NAME: {
        label: 'اسم القناة الرئيسية',
        help: 'الاسم المعروض للقناة الرئيسية في السجلات ومخرجات الحالة.'
      },
      BLUEBUBBLES_ALLOW_ALL_USERS: {
        label: 'السماح لكل مستخدمي iMessage',
        help: 'عند التفعيل، يتم تجاوز قائمة سماح BlueBubbles.'
      },
      MATTERMOST_ALLOW_ALL_USERS: { label: 'السماح لكل مستخدمي Mattermost' },
      MATTERMOST_HOME_CHANNEL: { label: 'القناة الرئيسية' },
      QQ_ALLOW_ALL_USERS: { label: 'السماح لكل مستخدمي QQ' },
      QQBOT_HOME_CHANNEL: { label: 'قناة QQ الرئيسية', help: 'القناة أو المجموعة الافتراضية لتسليم المهام المجدولة.' },
      QQBOT_HOME_CHANNEL_NAME: { label: 'اسم قناة QQ الرئيسية' },
      SLACK_BOT_TOKEN: {
        label: 'رمز بوت Slack',
        help: 'استخدم رمز البوت من OAuth & Permissions بعد تثبيت تطبيق Slack الخاص بك.',
        placeholder: 'الصق رمز بوت Slack'
      },
      SLACK_APP_TOKEN: {
        label: 'رمز تطبيق Slack',
        help: 'استخدم الرمز على مستوى التطبيق المطلوب لوضع Socket Mode.',
        placeholder: 'الصق رمز تطبيق Slack'
      },
      SLACK_ALLOWED_USERS: { label: 'معرّفات مستخدمي Slack المسموح بهم', help: 'موصى به. معرّفات مستخدمي Slack مفصولة بفواصل.' },
      MATTERMOST_URL: { label: 'عنوان الخادم', placeholder: 'https://mattermost.example.com' },
      MATTERMOST_TOKEN: { label: 'رمز البوت' },
      MATTERMOST_ALLOWED_USERS: {
        label: 'معرّفات المستخدمين المسموح بهم',
        help: 'موصى به. معرّفات مستخدمي Mattermost مفصولة بفواصل.'
      },
      MATRIX_HOMESERVER: { label: 'عنوان الخادم المضيف', placeholder: 'https://matrix.org' },
      MATRIX_ACCESS_TOKEN: { label: 'رمز الوصول' },
      MATRIX_USER_ID: { label: 'معرّف مستخدم البوت', placeholder: '@hermes:example.org' },
      MATRIX_ALLOWED_USERS: {
        label: 'معرّفات مستخدمي Matrix المسموح بهم',
        help: 'موصى به. معرّفات المستخدمين بصيغة @user:server مفصولة بفواصل.'
      },
      SIGNAL_HTTP_URL: {
        label: 'عنوان جسر Signal',
        placeholder: 'http://127.0.0.1:8080',
        help: 'عنوان جسر signal-cli REST قيد التشغيل.'
      },
      SIGNAL_ACCOUNT: { label: 'رقم الهاتف', help: 'الرقم المسجَّل في جسر signal-cli الخاص بك.' },
      SIGNAL_ALLOWED_USERS: { label: 'مستخدمو Signal المسموح بهم', help: 'موصى به. معرّفات Signal مفصولة بفواصل.' },
      WHATSAPP_ENABLED: {
        label: 'تفعيل جسر WhatsApp',
        help: 'يُضبط تلقائيًا بواسطة المفتاح أدناه. اتركه كما هو ما لم تكن متأكدًا من حاجتك إليه.'
      },
      WHATSAPP_MODE: { label: 'وضع الجسر' },
      WHATSAPP_ALLOWED_USERS: {
        label: 'مستخدمو WhatsApp المسموح بهم',
        help: 'موصى به. أرقام هواتف أو معرّفات WhatsApp مفصولة بفواصل.'
      }
    },
    platformIntro: {}
  },

  profiles: {
    close: 'إغلاق الملفات الشخصية',
    nameHint: 'أحرف إنجليزية صغيرة وأرقام وشرطات وشرطات سفلية. يجب أن يبدأ بحرف أو رقم.',
    title: 'الملفات الشخصية',
    count: count =>
      arPlural(count, {
        one: 'ملف شخصي واحد',
        two: 'ملفان شخصيان',
        few: `${count} ملفات شخصية`,
        many: `${count} ملفًا شخصيًا`,
        other: `${count} ملف شخصي`
      }),
    search: 'البحث في الملفات الشخصية...',
    loading: 'جارٍ تحميل الملفات الشخصية...',
    newProfile: 'ملف شخصي جديد',
    allProfiles: 'كل الملفات الشخصية',
    showAllProfiles: 'إظهار كل الملفات الشخصية',
    switchToProfile: name => `التبديل إلى ${name}`,
    manageProfiles: 'إدارة الملفات الشخصية...',
    actionsFor: name => `إجراءات لـ${name}`,
    color: 'اللون...',
    colorFor: name => `لون ${name}`,
    setColor: color => `تعيين اللون ${color}`,
    autoColor: 'تلقائي',
    noProfiles: 'لا توجد ملفات شخصية بعد.',
    selectPrompt: 'اختر ملفًا شخصيًا لعرض تفاصيله.',
    refresh: 'تحديث الملفات الشخصية',
    refreshing: 'جارٍ تحديث الملفات الشخصية',
    default: 'افتراضي',
    skills: count =>
      arPlural(count, { one: 'مهارة واحدة', two: 'مهارتان', few: `${count} مهارات`, many: `${count} مهارة`, other: `${count} مهارة` }),
    env: 'env',
    defaultBadge: 'افتراضي',
    rename: 'إعادة تسمية',
    copySetup: 'نسخ الإعداد',
    copying: 'جارٍ النسخ...',
    modelLabel: 'النموذج',
    skillsLabel: 'المهارات',
    notSet: 'غير محدد',
    soulDesc: 'توجيهات موجّه النظام والشخصية المدمجة في هذا الملف الشخصي.',
    soulOptional: 'اختياري',
    soulPlaceholder: mode => `موجّه النظام / الشخصية لهذا الملف الشخصي.\nاتركه فارغًا للاحتفاظ بافتراضي ${mode}.`,
    soulPlaceholderCloned: 'مستنسخ',
    soulPlaceholderEmpty: 'فارغ',
    unsavedChanges: 'تغييرات غير محفوظة',
    loadingSoul: 'جارٍ تحميل SOUL.md...',
    emptySoul: 'SOUL.md فارغ — ابدأ كتابة الشخصية...',
    saving: 'جارٍ الحفظ...',
    saveSoul: 'حفظ SOUL.md',
    deleteTitle: 'حذف الملف الشخصي؟',
    deleteDescPrefix: 'سيؤدي هذا إلى حذف ',
    deleteDescMid: ' وإزالة مجلده ',
    deleteDescSuffix: '. لا يمكن التراجع عن هذا.',
    deleting: 'جارٍ الحذف...',
    createDesc: 'الملفات الشخصية بيئات Simplicio مستقلة: إعداد ومهارات وSOUL.md منفصلة.',
    nameLabel: 'الاسم',
    cloneFrom: 'استنساخ من',
    cloneFromNone: 'بلا (فارغ)',
    cloneFromDesc: 'ينسخ الإعداد والمهارات وSOUL.md من الملف الشخصي المصدر المحدد.',
    cloneFromDefault: 'استنساخ من الافتراضي',
    cloneFromDefaultDesc: 'انسخ الإعداد والمهارات وSOUL.md من ملفك الشخصي الافتراضي.',
    invalidName: hint => `اسم غير صالح. ${hint}`,
    nameRequired: 'الاسم مطلوب.',
    creating: 'جارٍ الإنشاء...',
    createAction: 'إنشاء ملف شخصي',
    renameTitle: 'إعادة تسمية الملف الشخصي',
    renameDescPrefix: 'إعادة التسمية تحدّث مجلد الملف الشخصي وأي نصوص برمجية غلافية في ',
    renameDescSuffix: '.',
    newNameLabel: 'الاسم الجديد',
    renaming: 'جارٍ إعادة التسمية...',
    created: 'تم إنشاء الملف الشخصي',
    renamed: 'تمت إعادة تسمية الملف الشخصي',
    deleted: 'تم حذف الملف الشخصي',
    setupCopied: 'تم نسخ أمر الإعداد',
    soulSaved: 'تم حفظ SOUL.md',
    failedLoad: 'فشل تحميل الملفات الشخصية',
    failedDelete: 'فشل حذف الملف الشخصي',
    failedCopy: 'فشل نسخ أمر الإعداد',
    failedLoadSoul: 'فشل تحميل SOUL.md',
    failedSaveSoul: 'فشل حفظ SOUL.md',
    failedCreate: 'فشل إنشاء الملف الشخصي',
    failedRename: 'فشل إعادة تسمية الملف الشخصي'
  },

  cron: {
    close: 'إغلاق المهام المجدولة',
    title: 'المهام المجدولة',
    count: count =>
      arPlural(count, { one: 'مهمة واحدة', two: 'مهمتان', few: `${count} مهام`, many: `${count} مهمة`, other: `${count} مهمة` }),
    search: 'البحث في المهام المجدولة...',
    loading: 'جارٍ تحميل المهام المجدولة...',
    states: {
      enabled: 'مفعَّلة',
      scheduled: 'مجدولة',
      running: 'قيد التشغيل',
      paused: 'متوقفة مؤقتًا',
      disabled: 'معطَّلة',
      error: 'خطأ',
      completed: 'مكتملة'
    },
    deliveryLabels: {
      local: 'سطح المكتب هذا',
      telegram: 'Telegram',
      discord: 'Discord',
      slack: 'Slack',
      email: 'البريد الإلكتروني'
    },
    scheduleLabels: {
      daily: 'يوميًا',
      weekdays: 'أيام الأسبوع',
      weekly: 'أسبوعيًا',
      monthly: 'شهريًا',
      hourly: 'كل ساعة',
      'every-15-minutes': 'كل 15 دقيقة',
      custom: 'مخصص'
    },
    scheduleHints: {
      daily: 'كل يوم الساعة 9:00 صباحًا',
      weekdays: 'من الاثنين إلى الجمعة الساعة 9:00 صباحًا',
      weekly: 'كل يوم اثنين الساعة 9:00 صباحًا',
      monthly: 'اليوم الأول من كل شهر الساعة 9:00 صباحًا',
      hourly: 'في بداية كل ساعة',
      'every-15-minutes': 'كل 15 دقيقة',
      custom: 'صيغة cron أو لغة طبيعية'
    },
    days: {
      '0': 'الأحد',
      '1': 'الاثنين',
      '2': 'الثلاثاء',
      '3': 'الأربعاء',
      '4': 'الخميس',
      '5': 'الجمعة',
      '6': 'السبت',
      '7': 'الأحد'
    },
    dayFallback: value => `اليوم ${value}`,
    everyDayAt: time => `كل يوم الساعة ${time}`,
    weekdaysAt: time => `أيام الأسبوع الساعة ${time}`,
    everyDayOfWeekAt: (day, time) => `كل ${day} الساعة ${time}`,
    monthlyOnDayAt: (dayOfMonth, time) => `شهريًا في اليوم ${dayOfMonth} الساعة ${time}`,
    topOfHour: 'في بداية كل ساعة',
    everyHourAt: minute => `كل ساعة عند الدقيقة :${minute}`,
    newCron: 'مهمة مجدولة جديدة',
    emptyDescNew:
      'جدول موجّهًا للتشغيل وفق تعبير cron. سيشغّله Simplicio ويسلّم النتائج إلى الوجهة التي تختارها.',
    emptyDescSearch: 'جرّب استعلام بحث أوسع.',
    emptyTitleNew: 'لا توجد مهام مجدولة بعد',
    emptyTitleSearch: 'لا توجد نتائج مطابقة',
    last: 'الأخيرة:',
    next: 'التالية:',
    noRuns: 'لا توجد عمليات تشغيل بعد',
    manage: 'إدارة',
    showRuns: 'إظهار عمليات التشغيل',
    hideRuns: 'إخفاء عمليات التشغيل',
    runHistory: 'سجل التشغيل',
    actionsFor: title => `إجراءات لـ${title}`,
    actionsTitle: 'إجراءات المهمة المجدولة',
    resume: 'استئناف المهمة',
    pause: 'إيقاف المهمة مؤقتًا',
    resumeTitle: 'استئناف',
    pauseTitle: 'إيقاف مؤقت',
    triggerNow: 'التشغيل الآن',
    edit: 'تعديل المهمة',
    deleteTitle: 'حذف المهمة المجدولة؟',
    deleteDescPrefix: 'سيؤدي هذا إلى إزالة ',
    deleteDescSuffix: ' نهائيًا. ستتوقف عن العمل فورًا.',
    deleting: 'جارٍ الحذف...',
    resumed: 'تم استئناف المهمة',
    paused: 'أُوقفت المهمة مؤقتًا',
    triggered: 'تم تشغيل المهمة',
    deleted: 'تم حذف المهمة',
    created: 'تم إنشاء المهمة',
    updated: 'تم تحديث المهمة',
    failedLoad: 'فشل تحميل المهام المجدولة',
    failedUpdate: 'فشل تحديث المهمة المجدولة',
    failedTrigger: 'فشل تشغيل المهمة المجدولة',
    failedDelete: 'فشل حذف المهمة المجدولة',
    failedSave: 'فشل حفظ المهمة المجدولة',
    editTitle: 'تعديل المهمة المجدولة',
    createTitle: 'مهمة مجدولة جديدة',
    editDesc: 'حدّث الجدول أو الموجّه أو وجهة التسليم. تسري التغييرات في التشغيل التالي.',
    createDesc: 'جدول موجّهًا للتشغيل تلقائيًا. استخدم صيغة cron أو عبارة طبيعية مثل "كل 15 دقيقة".',
    nameLabel: 'الاسم',
    namePlaceholder: 'الملخص الصباحي',
    promptLabel: 'الموجّه',
    promptPlaceholder: 'لخّص محادثات Slack غير المقروءة وأرسل لي أفضل 5 عبر البريد...',
    frequencyLabel: 'التكرار',
    deliverLabel: 'التسليم إلى',
    customScheduleLabel: 'جدول مخصص',
    customPlaceholder: '0 9 * * * أو أيام الأسبوع الساعة 9 صباحًا',
    customHint: 'تعبير cron، أو عبارات مثل "كل ساعة" أو "أيام الأسبوع الساعة 9 صباحًا".',
    optional: 'اختياري',
    promptScheduleRequired: 'الموجّه والجدول مطلوبان.',
    saveChanges: 'حفظ التغييرات',
    createAction: 'إنشاء مهمة مجدولة'
  },

  artifacts: {
    search: 'البحث في المخرجات...',
    refresh: 'تحديث المخرجات',
    refreshing: 'جارٍ تحديث المخرجات',
    indexing: 'جارٍ فهرسة مخرجات الجلسات الأخيرة',
    tabAll: 'الكل',
    tabImages: 'الصور',
    tabFiles: 'الملفات',
    tabLinks: 'الروابط',
    noArtifactsTitle: 'لم يُعثر على مخرجات',
    noArtifactsDesc: 'ستظهر هنا الصور المُولَّدة ومخرجات الملفات عند إنتاجها من الجلسات.',
    failedLoad: 'فشل تحميل المخرجات',
    openFailed: 'فشل الفتح',
    itemsImage: 'صور',
    itemsLink: 'روابط',
    itemsFile: 'ملفات',
    itemsGeneric: 'عناصر',
    zero: '0',
    rangeOf: (start, end, total) => `${start}-${end} من ${total}`,
    goToPage: (itemLabel, page) => `الانتقال إلى صفحة ${itemLabel} ${page}`,
    colTitleLink: 'عنوان الرابط',
    colTitleFile: 'الاسم',
    colTitleDefault: 'العنوان / الاسم',
    colLocationLink: 'العنوان URL',
    colLocationFile: 'المسار',
    colLocationDefault: 'الموقع',
    colSession: 'الجلسة',
    kindImage: 'صورة',
    kindFile: 'ملف',
    kindLink: 'رابط',
    chat: 'المحادثة',
    copyUrl: 'نسخ العنوان',
    copyPath: 'نسخ المسار'
  },

  integrations: {
    title: 'التكاملات',
    subtitle: 'نشر خادم Simplicio MCP إلى محرراتك ووكلائك المثبَّتين.',
    backendUnavailable: 'جسر Simplicio غير متاح — لا يمكن التحقق من حالة التكامل من هذه النافذة.',
    daemonTitle: 'خادم Simplicio MCP',
    daemonAlwaysOn: 'خادم MCP محلي، يعمل دائمًا',
    daemonRunning: 'نشط',
    daemonStopped: 'متوقف',
    daemonPid: pid => `PID ${pid}`,
    daemonUptime: uptime => `يعمل منذ ${uptime}`,
    daemonRestarts: count =>
      arPlural(count, {
        one: 'إعادة تشغيل واحدة',
        two: 'إعادتا تشغيل',
        few: `${count} إعادات تشغيل`,
        many: `${count} إعادة تشغيل`,
        other: `${count} إعادة تشغيل`
      }),
    daemonLastError: message => `آخر خطأ: ${message}`,
    editorsHeading: 'المحررات والوكلاء',
    deployAll: 'نشر إلى الكل',
    deploying: 'جارٍ النشر...',
    deployedTitle: 'تم نشر خادم MCP',
    deployedSummary: (registered, skipped) =>
      skipped > 0 ? `${registered} مسجَّل، ${skipped} متخطى` : `${registered} مسجَّل`,
    deployFailedTitle: 'فشل النشر',
    deployResultRegisteredLabel: 'مسجَّل:',
    deployResultSkippedLabel: 'متخطى:',
    deployResultNoneRegistered: 'لم يُسجَّل أي محرر.',
    restartNote: 'أعد تشغيل محررك أو وكيلك لتحميل الخادم.',
    detectFailedTitle: 'فشل اكتشاف المحررات',
    noEditorsFound: 'لم يُكتشف أي محرر على هذا الجهاز.',
    configPathUnknown: 'لم يُبلَّغ عن مسار إعداد',
    stateConnected: 'متصل',
    stateInstalled: 'مثبَّت، غير متصل',
    stateNotInstalled: 'غير مثبَّت'
  },

  sidebar: {
    nav: {
      'new-session': 'جلسة جديدة',
      skills: 'الإمكانيات',
      messaging: 'المراسلة',
      artifacts: 'المخرجات',
      integrations: 'التكاملات',
      savings: 'اقتصاد الرموز'
    },
    searchAria: 'البحث في الجلسات',
    searchPlaceholder: 'البحث في الجلسات…',
    clearSearch: 'مسح البحث',
    noMatch: query => `لا توجد جلسات مطابقة لـ「${query}」.`,
    results: 'النتائج',
    pinned: 'مثبَّتة',
    sessions: 'الجلسات',
    cronJobs: 'المهام المجدولة',
    groupAriaGrouped: 'إظهار الجلسات كقائمة واحدة',
    groupAriaUngrouped: 'تجميع الجلسات حسب مساحة العمل',
    showProjects: 'إظهار المشاريع',
    showSessions: 'إظهار الجلسات',
    groupTitleGrouped: 'إلغاء تجميع الجلسات',
    groupTitleUngrouped: 'التجميع حسب مساحة العمل',
    allPinned: 'كل شيء هنا مثبَّت. ألغِ تثبيت محادثة لإظهارها في الأخيرة.',
    shiftClickHint: 'اضغط Shift مع النقر على محادثة لتثبيتها',
    noWorkspace: 'لا توجد مساحة عمل',
    noProject: 'لا يوجد مشروع',
    projectEmpty: 'لا توجد جلسات بعد',
    noSessions: 'لا توجد جلسات بعد',
    projects: {
      sectionLabel: 'المشاريع',
      newButton: 'مشروع جديد',
      createTitle: 'مشروع جديد',
      createDesc: 'سمِّ مساحة عمل وأضف مجلدًا واحدًا أو أكثر.',
      renameTitle: 'إعادة تسمية المشروع',
      addFolderTitle: 'إضافة مجلد',
      namePlaceholder: 'مثال: Skunkworks',
      foldersLabel: 'المجلدات',
      ideaLabel: 'الفكرة',
      ideaPlaceholder: 'ما موضوع هذا المشروع؟ (يُحفظ في IDEA.md)',
      ideaGenerate: 'توليد فكرة',
      ideaGenerating: 'جارٍ التوليد…',
      ideaShuffle: 'خلط القوالب',
      noFolders: 'لم تُضَف أي مجلدات بعد.',
      addFolder: 'إضافة مجلد',
      primaryBadge: 'أساسي',
      removeFolder: 'إزالة',
      create: 'إنشاء',
      menu: 'إجراءات المشروع',
      menuRename: 'إعادة تسمية',
      menuAppearance: 'المظهر',
      noColor: 'بلا لون',
      menuAddFolder: 'إضافة مجلد',
      menuSetActive: 'تعيين كنشط',
      menuDelete: 'حذف',
      reveal: 'إظهار في المجلد',
      copyPath: 'نسخ المسار',
      removeFromSidebar: 'إخفاء من الشريط الجانبي',
      createFailed: 'تعذّر إنشاء المشروع',
      staleBackend:
        'حدّث خادم Simplicio الخلفي لإنشاء مشاريع — خادمك الخلفي أقدم من تطبيق سطح المكتب هذا (الإعدادات ← التحديثات ← الخادم الخلفي).',
      deleteConfirm: 'يزيل هذا المشروع المحفوظ من Simplicio. تبقى الملفات ومستودعات git وأشجار العمل دون تغيير.',
      startWork: 'شجرة عمل جديدة',
      newWorktreeTitle: 'شجرة عمل جديدة',
      newWorktreeDesc: 'سمِّ الفرع لشجرة العمل هذه.',
      branchPlaceholder: 'مثال: my-feature',
      startWorkFailed: 'تعذّر إنشاء شجرة العمل',
      convertBranch: 'تحويل فرع…',
      convertBranchTitle: 'تحويل فرع',
      convertBranchDesc: 'افتح الفروع المسحوبة بالفعل، أو أنشئ شجرة عمل لفرع حر.',
      convertBranchPlaceholder: 'البحث في الفروع…',
      convertBranchInstead: 'تحويل فرع موجود بدلًا من ذلك',
      branchOpenExisting: 'فتح',
      branchSwitchHome: 'التبديل إلى الرئيسي',
      branchCreateWorktree: 'شجرة عمل جديدة',
      branchesLoading: 'جارٍ تحميل الفروع…',
      noBranches: 'لم يُعثر على فروع',
      removeWorktree: 'إزالة شجرة العمل',
      removeWorktreeFailed: 'تعذّر إزالة شجرة العمل (تغييرات غير ملتزَمة؟)',
      removeWorktreeConfirm:
        'أزلها من git (يحذف مجلد شجرة العمل؛ يبقى الفرع)، أو أخفِ المسار فقط من الشريط الجانبي واترك شجرة العمل على القرص.',
      removeWorktreeDirty:
        'تحتوي شجرة العمل هذه على تغييرات غير ملتزَمة. أزلها قسرًا (يتجاهل تلك التغييرات)، أو أخفِ المسار فقط واحتفظ بها على القرص.',
      forceRemove: 'إزالة قسرية',
      enter: label => `فتح ${label}`,
      reorder: label => `إعادة ترتيب ${label}`,
      toggle: label => `تبديل جلسات ${label}`,
      back: 'كل المشاريع'
    },
    newSessionIn: label => `جلسة جديدة في ${label}`,
    showMoreIn: (count, label) =>
      arPlural(count, {
        one: `إظهار جلسة واحدة إضافية في ${label}`,
        two: `إظهار جلستين إضافيتين في ${label}`,
        few: `إظهار ${count} جلسات إضافية في ${label}`,
        many: `إظهار ${count} جلسة إضافية في ${label}`,
        other: `إظهار ${count} جلسة إضافية في ${label}`
      }),
    loading: 'جارٍ التحميل…',
    loadMore: 'تحميل المزيد',
    loadCount: step => `تحميل ${step} إضافية`,
    row: {
      pin: 'تثبيت',
      unpin: 'إلغاء التثبيت',
      copyId: 'نسخ المعرّف',
      export: 'تصدير',
      branchFrom: 'تفريع',
      rename: 'إعادة تسمية',
      archive: 'أرشفة',
      newWindow: 'نافذة جديدة',
      copyIdFailed: 'تعذّر نسخ معرّف الجلسة',
      actionsFor: title => `إجراءات لـ${title}`,
      sessionActions: 'إجراءات الجلسة',
      sessionRunning: 'الجلسة قيد التشغيل',
      needsInput: 'تحتاج إدخالك',
      waitingForAnswer: 'بانتظار إجابتك',
      handoffOrigin: platform => `سُلِّمت من ${platform}`,
      renamed: 'تمت إعادة التسمية',
      renameFailed: 'فشلت إعادة التسمية',
      renameTitle: 'إعادة تسمية الجلسة',
      renameDesc: 'أعطِ هذه المحادثة عنوانًا مميزًا. اتركه فارغًا للمسح.',
      untitledPlaceholder: 'جلسة بلا عنوان',
      ageNow: 'الآن',
      ageDay: 'ي',
      ageHour: 'س',
      ageMin: 'د'
    }
  },

  composer: {
    message: 'رسالة',
    wakingProfile: profile => `جارٍ تنشيط ${profile}…`,
    placeholderStarting: 'جارٍ تشغيل Simplicio...',
    placeholderReconnecting: 'جارٍ إعادة الاتصال بـSimplicio…',
    placeholderFollowUp: 'أرسل متابعة',
    newSessionPlaceholders: [
      'ما الذي سنبنيه؟',
      'أعطِ Simplicio مهمة',
      'ما الذي يشغل بالك؟',
      'صف ما تحتاجه',
      'ما الذي سنتناوله؟',
      'اسأل أي شيء',
      'ابدأ بهدف'
    ],
    followUpPlaceholders: [
      'أرسل متابعة',
      'أضف مزيدًا من السياق',
      'حسِّن الطلب',
      'ما التالي؟',
      'واصل',
      'ادفعه أبعد',
      'عدّل أو تابع'
    ],
    startVoice: 'بدء محادثة صوتية',
    queueMessage: 'إضافة الرسالة إلى قائمة الانتظار',
    steer: 'توجيه التشغيل الحالي',
    stop: 'إيقاف',
    send: 'إرسال',
    speaking: 'يتحدث',
    transcribing: 'جارٍ التفريغ',
    thinking: 'يفكر',
    muted: 'مكتوم',
    listening: 'يستمع',
    muteMic: 'كتم الميكروفون',
    unmuteMic: 'إلغاء كتم الميكروفون',
    stopListening: 'إيقاف الاستماع والإرسال',
    stopShort: 'إيقاف',
    endConversation: 'إنهاء المحادثة الصوتية',
    endShort: 'إنهاء',
    stopDictation: 'إيقاف الإملاء',
    transcribingDictation: 'جارٍ تفريغ الإملاء',
    voiceDictation: 'الإملاء الصوتي',
    speakReplies: 'قراءة الردود بصوت عالٍ',
    stopSpeakingReplies: 'إيقاف قراءة الردود بصوت عالٍ',
    lookupLoading: 'جارٍ البحث…',
    lookupNoMatches: 'لا توجد نتائج مطابقة.',
    lookupTry: 'جرّب',
    lookupOr: 'أو',
    commonCommands: 'الأوامر الشائعة',
    hotkeys: 'اختصارات لوحة المفاتيح',
    helpFooter: 'يفتح اللوحة الكاملة · Backspace للإغلاق',
    commandDescs: {
      '/help': 'قائمة كاملة بالأوامر واختصارات لوحة المفاتيح',
      '/clear': 'بدء جلسة جديدة',
      '/resume': 'استئناف جلسة سابقة',
      '/details': 'التحكم في مستوى تفاصيل النسخة',
      '/copy': 'نسخ التحديد أو آخر رسالة من المساعد',
      '/quit': 'الخروج من Simplicio'
    },
    hotkeyDescs: {
      'composer.mention': 'الإشارة إلى ملفات ومجلدات وروابط وgit',
      'composer.slash': 'لوحة أوامر الشرطة المائلة',
      'composer.help': 'هذه المساعدة السريعة (احذف للإغلاق)',
      'composer.sendNewline': 'إرسال · Shift+Enter لسطر جديد',
      'composer.sendQueued': 'إرسال الدور التالي في قائمة الانتظار',
      'keybinds.openPanel': 'كل اختصارات لوحة المفاتيح',
      'composer.cancel': 'إغلاق النافذة المنبثقة · إلغاء التشغيل',
      'composer.history': 'التنقل بين النوافذ المنبثقة / السجل'
    },
    attachUrlTitle: 'إرفاق عنوان URL',
    attachUrlDesc: 'سيجلب Simplicio الصفحة ويضمّنها كسياق لهذه الجولة.',
    urlPlaceholder: 'https://example.com/post',
    urlHintPre: 'أدرج العنوان الكامل، مثل ',
    attach: 'إرفاق',
    queued: count => `${count} في الانتظار`,
    attachmentOnly: 'جولة مرفق فقط',
    emptyTurn: 'جولة فارغة',
    attachments: count =>
      arPlural(count, { one: 'مرفق واحد', two: 'مرفقان', few: `${count} مرفقات`, many: `${count} مرفقًا`, other: `${count} مرفق` }),
    editingInComposer: 'جارٍ التعديل في مربع الكتابة',
    editingQueuedInComposer: 'جارٍ تعديل دور في قائمة الانتظار داخل مربع الكتابة',
    queueEdit: 'تعديل',
    queueSendNext: 'التالي',
    queueSend: 'إرسال',
    queueDelete: 'حذف',
    queueStuckTitle: 'لم تُرسَل الرسالة في قائمة الانتظار',
    queueStuckBody: 'استمر دور في قائمة الانتظار بالفشل في الإرسال. لا يزال في قائمة الانتظار — جرّب إرساله مرة أخرى.',
    previewUnavailable: 'المعاينة غير متاحة',
    previewLabel: label => `معاينة ${label}`,
    couldNotPreview: label => `تعذّرت معاينة ${label}`,
    removeAttachment: label => `إزالة ${label}`,
    dictating: 'جارٍ الإملاء',
    preparingAudio: 'جارٍ تجهيز الصوت',
    speakingResponse: 'جارٍ نطق الرد',
    readingAloud: 'جارٍ القراءة بصوت عالٍ',
    themeSuggestions: 'اقتراحات سمة سطح المكتب',
    noMatchingThemes: 'لا توجد سمات مطابقة.',
    themeTryPre: 'جرّب ',
    themeTryPost: '.',
    attachLabel: 'إرفاق',
    files: 'ملفات…',
    folder: 'مجلد…',
    images: 'صور…',
    pasteImage: 'لصق صورة',
    url: 'رابط…',
    promptSnippets: 'مقتطفات الموجّهات…',
    tipPre: 'نصيحة: اكتب ',
    tipPost: ' للإشارة إلى الملفات ضمن النص.',
    snippetsTitle: 'مقتطفات الموجّهات',
    snippetsDesc: 'اختر موجّهًا جاهزًا لإدراجه في مربع الكتابة.',
    dropFiles: 'أفلت الملفات لإرفاقها',
    dropSession: 'أفلت لربط هذه المحادثة',
    snippets: {
      codeReview: {
        label: 'مراجعة الشيفرة',
        description: 'دقّق التغيير الحالي بحثًا عن الانحدارات والحالات الحدّية المفقودة والاختبارات الناقصة.',
        text: 'يرجى مراجعة هذا بحثًا عن الأخطاء والانحدارات والاختبارات الناقصة.'
      },
      implementationPlan: {
        label: 'خطة التنفيذ',
        description: 'حدّد نهجًا قبل لمس الشيفرة حتى يبقى الفرق مركّزًا.',
        text: 'يرجى وضع خطة تنفيذ موجزة قبل تغيير الشيفرة.'
      },
      explainThis: {
        label: 'اشرح هذا',
        description: 'اشرح كيفية عمل الشيفرة المحددة واربطها بالملفات الرئيسية.',
        text: 'يرجى شرح كيفية عمل هذا وتوجيهي إلى الملفات الرئيسية.'
      }
    }
  },

  statusStack: {
    agents: 'الوكلاء',
    background: count => `${count} بالخلفية`,
    subagents: count =>
      arPlural(count, {
        one: 'وكيل فرعي واحد',
        two: 'وكيلان فرعيان',
        few: `${count} وكلاء فرعيون`,
        many: `${count} وكيلًا فرعيًا`,
        other: `${count} وكيل فرعي`
      }),
    todos: (done, total) => `المهام ${done}/${total}`,
    running: 'قيد التشغيل',
    stop: 'إيقاف',
    dismiss: 'إغلاق',
    exit: code => `الخروج ${code}`,
    coding: {
      title: 'شجرة العمل',
      noBranch: 'لا يوجد فرع',
      detached: 'منفصل',
      clean: 'نظيف',
      changed: count =>
        arPlural(count, {
          one: 'ملف واحد معدَّل',
          two: 'ملفان معدَّلان',
          few: `${count} ملفات معدَّلة`,
          many: `${count} ملفًا معدَّلًا`,
          other: `${count} ملف معدَّل`
        }),
      ahead: count =>
        arPlural(count, {
          one: 'كوميت واحد متقدم',
          two: 'كوميتان متقدمان',
          few: `${count} كوميتات متقدمة`,
          many: `${count} كوميتًا متقدمًا`,
          other: `${count} كوميت متقدم`
        }),
      behind: count =>
        arPlural(count, {
          one: 'كوميت واحد متأخر',
          two: 'كوميتان متأخران',
          few: `${count} كوميتات متأخرة`,
          many: `${count} كوميتًا متأخرًا`,
          other: `${count} كوميت متأخر`
        }),
      review: 'مراجعة',
      close: 'إغلاق',
      openChanges: 'فتح التغييرات',
      openFile: 'فتح الملف',
      stage: 'تجهيز',
      unstage: 'إلغاء التجهيز',
      stageAll: 'تجهيز الكل',
      viewAsTree: 'عرض كشجرة',
      viewAsList: 'عرض كقائمة',
      revert: 'تراجع',
      revertAll: 'تراجع عن الكل',
      revertConfirm: 'تجاهل التغييرات على هذا الملف واستعادته إلى الحالة الملتزَمة؟ لا يمكن التراجع عن هذا.',
      revertAllConfirm: 'تجاهل كل التغييرات واستعادة الملفات إلى الحالة الملتزَمة؟ لا يمكن التراجع عن هذا.',
      staged: 'مُجهَّز',
      noChanges: 'لا توجد تغييرات',
      notRepo: 'ليس مستودع git',
      noDiff: 'لا يوجد فرق لعرضه',
      scopeUncommitted: 'غير ملتزَم',
      scopeBranch: 'الفرع',
      scopeLastTurn: 'الجولة الأخيرة',
      commit: 'Commit',
      commitAndPush: 'Commit ودفع',
      commitPlaceholder: 'الرسالة (⌘↵ لعمل Commit)',
      generateCommitMessage: 'توليد رسالة Commit',
      stopGenerating: 'إيقاف التوليد',
      createPr: 'إنشاء طلب سحب',
      openPr: 'فتح طلب السحب',
      ghMissing: 'ثبّت أداة سطر أوامر GitHub (gh) وسجّل الدخول لفتح طلبات السحب',
      agentShip: 'اطلب من Simplicio فتح طلب سحب',
      agentShipPrompt:
        'راجع التغييرات الحالية، والتزم بها برسالة commit تقليدية واضحة، وادفع الفرع، وافتح طلب سحب.',
      newBranch: 'فرع جديد',
      branchOffFrom: base => `فرع جديد من ${base}`,
      switchTo: branch => `التبديل إلى ${branch}`,
      switchFailed: branch => `تعذّر التبديل إلى ${branch}`,
      worktrees: 'أشجار العمل'
    }
  },

  updates: {
    stages: {
      idle: 'جارٍ التجهيز…',
      prepare: 'جارٍ التجهيز…',
      fetch: 'جارٍ التنزيل…',
      pull: 'أوشكنا على الانتهاء…',
      pydeps: 'جارٍ الإنهاء…',
      update: 'جارٍ تحديث Simplicio…',
      rebuild: 'جارٍ إعادة بناء تطبيق سطح المكتب…',
      restart: 'جارٍ إعادة تشغيل Simplicio…',
      done: 'اكتمل التحديث',
      manual: 'التحديث من الطرفية',
      guiSkew: 'حدّث تطبيق سطح المكتب',
      error: 'التحديث متوقف'
    },
    checking: 'جارٍ البحث عن تحديثات…',
    checkFailedTitle: 'تعذّر التحقق من التحديثات',
    tryAgain: 'إعادة المحاولة',
    notAvailableTitle: 'التحديث غير متاح',
    unsupportedMessage: 'لا يمكن لهذا الإصدار من Simplicio تحديث نفسه من داخل التطبيق.',
    connectionRetry: 'تحقق من اتصالك وأعد المحاولة.',
    latestBody: 'أنت تستخدم أحدث إصدار.',
    latestBodyBackend: 'يعمل الخادم الخلفي بأحدث إصدار.',
    allSetTitle: 'كل شيء جاهز',
    availableTitle: 'يتوفر تحديث جديد',
    availableBody: 'إصدار جديد من Simplicio جاهز للتثبيت.',
    availableTitleBackend: 'يتوفر تحديث للخادم الخلفي',
    availableBodyBackend: 'إصدار أحدث من خادم Simplicio المتصل جاهز للتثبيت.',
    availableBodyNoChangelog: 'يتوفر إصدار أحدث. ملاحظات الإصدار غير متاحة لنوع التثبيت هذا.',
    updateNow: 'التحديث الآن',
    maybeLater: 'ربما لاحقًا',
    moreChanges: count =>
      arPlural(count, {
        one: '+ تغيير واحد إضافي مُضمَّن.',
        two: '+ تغييران إضافيان مُضمَّنان.',
        few: `+ ${count} تغييرات إضافية مُضمَّنة.`,
        many: `+ ${count} تغييرًا إضافيًا مُضمَّنًا.`,
        other: `+ ${count} تغيير إضافي مُضمَّن.`
      }),
    manualTitle: 'التحديث من الطرفية',
    manualBody: 'ثبَّتّ Simplicio من سطر الأوامر، لذا تعمل التحديثات هناك أيضًا. الصق هذا في طرفيتك:',
    manualPickedUp: 'سيلتقط Simplicio الإصدار الجديد في المرة التالية التي تشغّله فيها.',
    guiSkewTitle: 'حدّث تطبيق سطح المكتب',
    guiSkewBody:
      'تم تحديث الخادم الخلفي، لكن حزمة تطبيق سطح المكتب هذه لم تتغيّر. حدّث أو أعد تثبيت تطبيق Simplicio Agent لسطح المكتب (AppImage / ‎.deb / ‎.rpm) ليطابقه.',
    copy: 'نسخ',
    copied: 'تم النسخ',
    done: 'تم',
    applyingBody:
      'يتولى مُحدِّث Simplicio الأمر في نافذته الخاصة ويعيد فتح Simplicio تلقائيًا عند الانتهاء. يرجى عدم إعادة فتح Simplicio بنفسك أثناء التحديث.',
    applyingBodyBackend: 'يطبّق الخادم الخلفي البعيد التحديث وسيعيد التشغيل. يعيد Simplicio الاتصال تلقائيًا عند عودته.',
    applyingClose: 'ستُغلَق هذه النافذة أثناء تشغيل التحديث، ثم يعيد Simplicio فتح نفسه.',
    errorTitle: 'لم يكتمل التحديث',
    errorBody: 'لا داعي للقلق — لم يضع شيء. يمكنك إعادة المحاولة الآن.',
    notNow: 'ليس الآن',
    applyStatus: {
      preparing: 'جارٍ تحديث الخادم الخلفي…',
      pulling: 'الخادم الخلفي قيد التحديث…',
      restarting: 'يعيد الخادم الخلفي التشغيل لتحميل التحديث…',
      notAvailable: 'التحديث غير متاح لهذا الخادم الخلفي.',
      failed: 'فشل تحديث الخادم الخلفي.',
      noReturn: 'لم يعد الخادم الخلفي إلى العمل. قد لا يكون التحديث قد اكتمل — تحقق من مضيف الخادم الخلفي.'
    }
  },

  install: {
    stageStates: {
      pending: 'قيد الانتظار',
      running: 'جارٍ التثبيت',
      succeeded: 'تم',
      skipped: 'تم التخطي',
      failed: 'فشل'
    },
    oneTimeTitle: 'يحتاج Simplicio إلى تثبيت لمرة واحدة',
    unsupportedDesc: platform =>
      `التثبيت التلقائي عند أول تشغيل غير متاح على ${platform} بعد. افتح الطرفية وشغّل الأمر أدناه، ثم أعد تشغيل هذا التطبيق. ستتخطى عمليات التشغيل اللاحقة هذه الخطوة.`,
    installCommand: 'أمر التثبيت',
    copyCommand: 'نسخ الأمر',
    viewDocs: 'عرض وثائق التثبيت',
    installTo: 'سيُثبَّت في',
    retryAfterRun: 'شغّلته -- إعادة المحاولة',
    failedTitle: 'فشل التثبيت',
    settingUpTitle: 'جارٍ إعداد Simplicio Agente',
    finishingTitle: 'جارٍ الإنهاء',
    failedDesc:
      'فشلت إحدى خطوات التثبيت. على Windows، قد يحدث هذا إذا كانت هناك نسخة أخرى من Simplicio CLI أو سطح المكتب قيد التشغيل. أوقف أي نسخ من Simplicio قيد التشغيل، ثم أعد المحاولة. تحقق من التفاصيل أدناه أو من سجل سطح المكتب للنسخة الكاملة.',
    activeDesc:
      'هذا إعداد لمرة واحدة. يقوم مثبِّت Simplicio بتنزيل التبعيات وضبط جهازك. ستتخطى عمليات التشغيل اللاحقة هذه الخطوة.',
    progress: (completed, total) => `اكتملت ${completed} من ${total} خطوات`,
    currentStage: stage => ` -- الآن: ${stage}`,
    fetchingManifest: 'جارٍ جلب بيان المثبِّت...',
    error: 'خطأ',
    hideOutput: 'إخفاء مخرجات المثبِّت',
    showOutput: 'إظهار مخرجات المثبِّت',
    lines: count =>
      arPlural(count, { one: 'سطر واحد', two: 'سطران', few: `${count} أسطر`, many: `${count} سطرًا`, other: `${count} سطر` }),
    noOutput: 'لا توجد مخرجات بعد.',
    cancelling: 'جارٍ الإلغاء...',
    cancelInstall: 'إلغاء التثبيت',
    transcriptSaved: 'حُفظت النسخة الكاملة في',
    copiedOutput: 'تم النسخ!',
    copyOutput: 'نسخ المخرجات',
    reloadRetry: 'إعادة التحميل والمحاولة مرة أخرى'
  },

  onboarding: {
    headerTitle: 'لنجهّزك مع Simplicio Agente',
    headerDesc: 'اربط مزوّد نموذج لبدء المحادثة. تحتاج معظم الخيارات نقرة واحدة فقط.',
    preparingInstall: 'ينهي Simplicio التثبيت. يستغرق هذا عادة أقل من دقيقة عند أول تشغيل.',
    starting: 'جارٍ تشغيل Simplicio…',
    lookingUpProviders: 'جارٍ البحث عن مزوّدين...',
    collapse: 'طي',
    otherProviders: 'مزوّدون آخرون',
    haveApiKey: 'لدي مفتاح API',
    chooseLater: 'سأختار مزوّدًا لاحقًا',
    recommended: 'موصى به',
    connected: 'متصل',
    featuredPitch: 'اشتراك واحد، أكثر من 300 نموذج متطور — الطريقة الموصى بها لتشغيل Simplicio',
    openRouterPitch: 'مفتاح واحد، مئات النماذج — خيار افتراضي جيد',
    apiKeyOptions: {
      openrouter: {
        short: 'مفتاح واحد، نماذج عديدة',
        description: 'يستضيف مئات النماذج خلف مفتاح واحد. خيار افتراضي جيد للتثبيتات الجديدة.'
      },
      openai: { short: 'نماذج من فئة GPT', description: 'وصول مباشر إلى نماذج OpenAI.' },
      gemini: { short: 'نماذج Gemini', description: 'وصول مباشر إلى نماذج Google Gemini.' },
      xai: { short: 'نماذج Grok', description: 'وصول مباشر إلى نماذج xAI Grok.' },
      local: {
        short: 'استضافة ذاتية',
        description: 'وجّه Simplicio إلى نقطة نهاية محلية أو ذاتية الاستضافة متوافقة مع OpenAI (vLLM، llama.cpp، Ollama، إلخ).'
      }
    },
    backToSignIn: 'العودة إلى تسجيل الدخول',
    getKey: 'الحصول على مفتاح',
    replaceCurrent: 'استبدال القيمة الحالية',
    pasteApiKey: 'لصق مفتاح API',
    localApiKeyPlaceholder: 'مفتاح API (اختياري — فقط إذا كانت نقطة النهاية تتطلبه)',
    couldNotSave: 'تعذّر حفظ بيانات الاعتماد.',
    connecting: 'جارٍ الاتصال',
    update: 'تحديث',
    flowSubtitles: {
      pkce: 'يفتح متصفحك لتسجيل الدخول، ثم يتابع هنا',
      device_code: 'يفتح صفحة تحقق في متصفحك — يتصل Simplicio تلقائيًا',
      loopback: 'يفتح متصفحك لتسجيل الدخول — يتصل Simplicio تلقائيًا',
      external: 'سجّل الدخول مرة واحدة في طرفيتك، ثم عد للمحادثة'
    },
    startingSignIn: provider => `جارٍ بدء تسجيل الدخول لـ${provider}...`,
    verifyingCode: provider => `جارٍ التحقق من رمزك مع ${provider}...`,
    connectedProvider: provider => `تم ربط ${provider}`,
    connectedPicking: provider => `تم ربط ${provider}. جارٍ اختيار نموذج افتراضي...`,
    signInFailed: 'فشل تسجيل الدخول. أعد المحاولة.',
    pickDifferentProvider: 'اختر مزوّدًا آخر',
    signInWith: provider => `تسجيل الدخول باستخدام ${provider}`,
    openedBrowser: provider => `فتحنا ${provider} في متصفحك.`,
    authorizeThere: 'فوِّض Simplicio هناك.',
    copyAuthCode: 'انسخ رمز التفويض والصقه أدناه.',
    pasteAuthCode: 'لصق رمز التفويض',
    reopenAuthPage: 'إعادة فتح صفحة التفويض',
    autoBrowser: provider =>
      `فتحنا ${provider} في متصفحك. فوِّض Simplicio هناك وستتصل تلقائيًا — لا حاجة لنسخ أو لصق أي شيء.`,
    reopenSignInPage: 'إعادة فتح صفحة تسجيل الدخول',
    waitingAuthorize: 'بانتظار تفويضك...',
    externalPending: provider =>
      `يسجّل ${provider} الدخول عبر أداة سطر أوامره الخاصة. شغّل هذا الأمر في طرفية، ثم عد واختر "لقد سجّلت الدخول":`,
    signedIn: 'لقد سجّلت الدخول',
    deviceCodeOpened: provider => `فتحنا ${provider} في متصفحك. أدخل هذا الرمز هناك:`,
    reopenVerification: 'إعادة فتح صفحة التحقق',
    copy: 'نسخ',
    defaultModel: 'النموذج الافتراضي',
    freeTier: 'المستوى المجاني',
    pro: 'احترافي',
    free: 'مجاني',
    price: (input, output) => `${input} إدخال / ${output} إخراج لكل مليون رمز`,
    change: 'تغيير',
    startChatting: 'ابدأ',
    docs: provider => `وثائق ${provider}`
  },

  modelPicker: {
    title: 'تبديل النموذج',
    current: 'الحالي:',
    unknown: '(غير معروف)',
    search: 'تصفية المزوّدين والنماذج...',
    noModels: 'لم يُعثر على نماذج.',
    addProvider: 'إضافة مزوّد',
    loadFailed: 'تعذّر تحميل النماذج',
    noAuthenticatedProviders: 'لا يوجد مزوّدون موثَّقون.',
    pro: 'احترافي',
    proNeedsSubscription: 'تحتاج النماذج الاحترافية إلى اشتراك Nous مدفوع.',
    free: 'مجاني',
    freeTier: 'المستوى المجاني',
    priceTitle: 'سعر الإدخال / الإخراج لكل مليون رمز'
  },

  modelVisibility: {
    title: 'النماذج',
    search: 'البحث في النماذج',
    noAuthenticatedProviders: 'لا يوجد مزوّدون موثَّقون.',
    addProvider: 'إضافة مزوّد…'
  },

  shell: {
    windowControls: 'عناصر تحكم النافذة',
    paneControls: 'عناصر تحكم اللوحة',
    appControls: 'عناصر تحكم التطبيق',
    modelMenu: {
      search: 'البحث في النماذج',
      noModels: 'لم يُعثر على نماذج',
      editModels: 'تعديل النماذج…',
      refreshModels: 'تحديث النماذج',
      fast: 'سريع',
      medium: 'متوسط'
    },
    modelOptions: {
      noOptions: 'لا توجد خيارات لهذا النموذج',
      options: 'الخيارات',
      thinking: 'التفكير',
      fast: 'سريع',
      effort: 'الجهد',
      minimal: 'ضئيل',
      low: 'منخفض',
      medium: 'متوسط',
      high: 'مرتفع',
      max: 'أقصى',
      updateFailed: 'فشل تحديث خيار النموذج',
      fastFailed: 'فشل تحديث الوضع السريع'
    },
    gatewayMenu: {
      gateway: 'البوابة',
      connected: 'متصل',
      connecting: 'جارٍ الاتصال',
      offline: 'غير متصل',
      inferenceReady: 'الاستدلال جاهز',
      inferenceNotReady: 'الاستدلال غير جاهز',
      checkingInference: 'جارٍ التحقق من الاستدلال',
      disconnected: 'منقطع',
      openSystem: 'فتح لوحة النظام',
      connection: label => `الاتصال: ${label}`,
      recentActivity: 'النشاط الأخير',
      viewAllLogs: 'عرض كل السجلات ←',
      messagingPlatforms: 'منصات المراسلة'
    },
    statusbar: {
      unknown: 'غير معروف',
      restart: 'إعادة تشغيل',
      update: 'تحديث',
      updateInProgress: 'التحديث قيد التنفيذ',
      commitsBehind: (count, branch) =>
        arPlural(count, {
          one: `كوميت واحد متأخر عن ${branch}`,
          two: `كوميتان متأخران عن ${branch}`,
          few: `${count} كوميتات متأخرة عن ${branch}`,
          many: `${count} كوميتًا متأخرًا عن ${branch}`,
          other: `${count} كوميت متأخر عن ${branch}`
        }),
      desktopVersion: version => `Simplicio Desktop v${version}`,
      backendVersion: version => `الخادم الخلفي v${version}`,
      clientLabel: version => `العميل v${version}`,
      backendLabel: version => `الخادم الخلفي v${version}`,
      commit: sha => `Commit ${sha}`,
      branch: branch => `الفرع ${branch}`,
      closeCommandCenter: 'إغلاق مركز الأوامر',
      openCommandCenter: 'فتح مركز الأوامر',
      showTerminal: 'إظهار الطرفية',
      hideTerminal: 'إخفاء الطرفية',
      gateway: 'البوابة',
      gatewayReady: 'جاهزة',
      gatewayNeedsSetup: 'تحتاج إعدادًا',
      gatewayChecking: 'جارٍ التحقق',
      gatewayConnecting: 'جارٍ الاتصال',
      gatewayOffline: 'غير متصلة',
      gatewayRestarting: 'جارٍ إعادة التشغيل…',
      gatewayTitle: 'حالة بوابة استدلال Simplicio',
      agents: 'الوكلاء',
      closeAgents: 'إغلاق الوكلاء',
      openAgents: 'فتح الوكلاء',
      subagents: count =>
        arPlural(count, {
          one: 'وكيل فرعي واحد',
          two: 'وكيلان فرعيان',
          few: `${count} وكلاء فرعيون`,
          many: `${count} وكيلًا فرعيًا`,
          other: `${count} وكيل فرعي`
        }),
      failed: count =>
        arPlural(count, {
          one: 'فشل واحد',
          two: 'فشلان',
          few: `${count} حالات فشل`,
          many: `${count} فشلًا`,
          other: `${count} فشل`
        }),
      running: count =>
        arPlural(count, {
          one: 'واحد قيد التشغيل',
          two: 'اثنان قيد التشغيل',
          few: `${count} قيد التشغيل`,
          many: `${count} قيد التشغيل`,
          other: `${count} قيد التشغيل`
        }),
      cron: 'المهام المجدولة',
      openCron: 'فتح المهام المجدولة',
      starmap: 'خريطة الذاكرة',
      openStarmap: 'فتح خريطة الذاكرة',
      turnRunning: 'قيد التشغيل',
      currentTurnElapsed: 'الوقت المنقضي للجولة الحالية',
      contextUsage: 'استخدام السياق',
      contextUsagePanel: {
        categories: {
          conversation: 'المحادثة',
          mcp: 'MCP',
          memory: 'الذاكرة',
          rules: 'القواعد',
          skills: 'المهارات',
          subagent_definitions: 'تعريفات الوكلاء الفرعيين',
          system_prompt: 'موجّه النظام',
          tool_definitions: 'تعريفات الأدوات'
        },
        empty: 'لا توجد بيانات سياق بعد',
        loading: 'جارٍ تحميل التفصيل…',
        percentFull: percent => `${percent}٪ ممتلئ`,
        title: 'استخدام السياق',
        tokenSummary: (used, max) => `${used} / ${max} رمز`
      },
      openContextUsage: 'فتح تفصيل استخدام السياق',
      session: 'الجلسة',
      runtimeSessionElapsed: 'الوقت المنقضي لجلسة بيئة التشغيل',
      yoloOn: 'YOLO مفعَّل — يوافَق تلقائيًا على الأوامر الخطرة. انقر للإيقاف. Shift+نقر يبدّله عالميًا.',
      yoloOff: 'YOLO معطَّل — انقر للموافقة التلقائية على الأوامر الخطرة. Shift+نقر يبدّله عالميًا.',
      modelNone: 'لا شيء',
      noModel: 'لا يوجد نموذج',
      switchModel: 'تبديل النموذج',
      openModelPicker: 'فتح مُنتقي النماذج',
      modelTitle: (provider, model) => `النموذج · ${provider}: ${model}`,
      providerModelTitle: (provider, model) => `${provider} · ${model}`
    }
  },

  rightSidebar: {
    aria: 'الشريط الجانبي الأيمن',
    panelsAria: 'لوحات الشريط الجانبي الأيمن',
    files: 'نظام الملفات',
    terminal: 'الطرفية',
    noFolderSelected: 'لم يُحدَّد مجلد',
    changeCwdTitle: 'تغيير مجلد العمل',
    remotePickerTitle: 'اختر مجلدًا بعيدًا',
    remotePickerDescription: 'تصفح المجلدات على الخادم الخلفي المتصل.',
    remotePickerSelect: 'اختيار المجلد',
    folderTip: cwd => `${cwd} — انقر لتغيير المجلد`,
    openFolder: 'فتح المجلد',
    refreshTree: 'تحديث الشجرة',
    collapseAll: 'طي كل المجلدات',
    previewUnavailable: 'المعاينة غير متاحة',
    couldNotPreview: path => `تعذّرت معاينة ${path}`,
    noProjectTitle: 'لا يوجد مشروع',
    noProjectBody: 'افتح مشروعًا لتصفح ملفاته ومراجعة تغييراته.',
    noProjectOpen: 'لا يوجد مشروع مفتوح',
    noDiffs: 'لا توجد فروقات',
    unreadableTitle: 'غير قابل للقراءة',
    unreadableBody: error => `تعذّرت قراءة هذا المجلد (${error}).`,
    emptyTitle: 'فارغ',
    emptyBody: 'هذا المجلد فارغ.',
    treeErrorTitle: 'خطأ في الشجرة',
    treeErrorBody: 'واجهت شجرة الملفات خطأ أثناء عرض هذا المجلد.',
    tryAgain: 'إعادة المحاولة',
    loadingTree: 'جارٍ تحميل شجرة الملفات',
    loadingFiles: 'جارٍ تحميل الملفات',
    terminalHide: 'إخفاء الطرفية',
    terminalsAria: 'الطرفيات',
    terminalNew: 'طرفية جديدة',
    terminalCloseOthers: 'إغلاق الأخرى',
    terminalCloseAll: 'إغلاق الكل',
    addToChat: 'إضافة إلى المحادثة'
  },

  preview: {
    tab: 'معاينة',
    closeTab: label => `إغلاق ${label}`,
    closeOthers: 'إغلاق الأخرى',
    closeToRight: 'إغلاق ما على اليمين',
    closeAll: 'إغلاق الكل',
    closePane: 'إغلاق لوحة المعاينة',
    loading: 'جارٍ تحميل المعاينة',
    unavailable: 'المعاينة غير متاحة',
    opening: 'جارٍ الفتح...',
    hide: 'إخفاء',
    openPreview: 'فتح المعاينة',
    openInBrowser: 'فتح في المتصفح',
    linkHint: '⌘/Ctrl-نقر لفتح لوحة المعاينة',
    sourceLineTitle: 'انقر للتحديد · Shift-نقر للتمديد · اسحب إلى مربع الكتابة',
    source: 'المصدر',
    renderedPreview: 'المعاينة',
    diff: 'الفرق',
    unknownSize: 'حجم غير معروف',
    binaryTitle: 'يبدو هذا ملفًا ثنائيًا',
    binaryBody: label => `قد تُظهر معاينة ${label} نصًا غير مقروء.`,
    largeTitle: 'هذا الملف كبير',
    largeBody: (label, size) => `${label} حجمه ${size}. سيُظهر Simplicio أول 512 كيلوبايت فقط.`,
    previewAnyway: 'معاينة على أي حال',
    truncated: 'يعرض أول 512 كيلوبايت.',
    noInlineTitle: 'لا توجد معاينة مضمّنة',
    noInlineBody: mimeType => `يمكن إرفاق ${mimeType || 'هذا النوع من الملفات'} كسياق رغم ذلك.`,
    edit: 'تعديل',
    editing: 'جارٍ التعديل',
    unsavedChanges: 'تغييرات غير محفوظة',
    saveFailed: message => `تعذّر الحفظ: ${message}`,
    diskChangedTitle: 'تغيّر الملف على القرص',
    diskChangedBody: 'تغيّر هذا الملف منذ أن فتحته. استبدله بنسختك، أو تجاهل تعديلاتك وأعد التحميل؟',
    overwrite: 'استبدال',
    discardReload: 'تجاهل وإعادة التحميل',
    console: {
      deselect: 'إلغاء تحديد الإدخال',
      select: 'تحديد الإدخال',
      copyFailed: 'تعذّر نسخ مخرجات الطرفية',
      copyEntry: 'نسخ هذا الإدخال',
      sendEntry: 'إرسال هذا الإدخال إلى المحادثة',
      messages: count =>
        arPlural(count, {
          one: 'رسالة طرفية واحدة',
          two: 'رسالتا طرفية',
          few: `${count} رسائل طرفية`,
          many: `${count} رسالة طرفية`,
          other: `${count} رسالة طرفية`
        }),
      resize: 'تغيير حجم طرفية المعاينة',
      title: 'طرفية المعاينة',
      selected: count =>
        arPlural(count, {
          one: 'واحد محدَّد',
          two: 'اثنان محدَّدان',
          few: `${count} محدَّدة`,
          many: `${count} محدَّدًا`,
          other: `${count} محدَّد`
        }),
      sendToChat: 'إرسال إلى المحادثة',
      copySelected: 'نسخ المحدَّد إلى الحافظة',
      copyAll: 'نسخ الكل إلى الحافظة',
      copy: 'نسخ',
      clear: 'مسح',
      empty: 'لا توجد رسائل طرفية بعد.',
      promptHeader: 'طرفية المعاينة:',
      sentTitle: 'أُرسل إلى المحادثة',
      sentMessage: count =>
        arPlural(count, {
          one: 'أُضيف إدخال سجل واحد إلى مربع الكتابة',
          two: 'أُضيف إدخالا سجل إلى مربع الكتابة',
          few: `أُضيفت ${count} إدخالات سجل إلى مربع الكتابة`,
          many: `أُضيف ${count} إدخال سجل إلى مربع الكتابة`,
          other: `أُضيف ${count} إدخال سجل إلى مربع الكتابة`
        })
    },
    web: {
      appFailedToBoot: 'فشل تشغيل تطبيق المعاينة',
      serverNotFound: 'الخادم غير موجود',
      failedToLoad: 'فشل تحميل المعاينة',
      tryAgain: 'إعادة المحاولة',
      restarting: 'Simplicio يعيد التشغيل...',
      askRestart: 'اطلب من Simplicio إعادة تشغيل الخادم',
      lookingRestart: taskId => `يبحث Simplicio عن خادم معاينة لإعادة تشغيله (${taskId})`,
      restartingTitle: 'جارٍ إعادة تشغيل خادم المعاينة',
      restartingMessage: 'يعمل Simplicio في الخلفية. راقب طرفية المعاينة لمتابعة التقدم.',
      startRestartFailed: message => `تعذّر بدء إعادة تشغيل الخادم: ${message}`,
      restartFailed: 'فشلت إعادة تشغيل الخادم',
      hideConsole: 'إخفاء طرفية المعاينة',
      showConsole: 'إظهار طرفية المعاينة',
      hideDevTools: 'إخفاء أدوات مطوري المعاينة',
      openDevTools: 'فتح أدوات مطوري المعاينة',
      finishedRestarting: message => `أنهى Simplicio إعادة تشغيل خادم المعاينة${message ? `: ${message}` : ''}`,
      failedRestarting: message => `فشلت إعادة تشغيل الخادم: ${message}`,
      unknownError: 'خطأ غير معروف',
      restartedTitle: 'أُعيد تشغيل خادم المعاينة',
      reloadingNow: 'جارٍ إعادة تحميل المعاينة الآن.',
      restartFailedTitle: 'فشلت إعادة تشغيل المعاينة',
      restartFailedMessage: 'تعذّر على Simplicio إعادة تشغيل الخادم.',
      stillWorking:
        'لا يزال Simplicio يعمل، لكن لم تصل بعد نتيجة إعادة التشغيل. قد يكون أمر الخادم يعمل في المقدمة.',
      workspaceReloading: 'تغيّرت مساحة العمل، جارٍ إعادة تحميل المعاينة',
      fileChanged: url => `تغيّر الملف، جارٍ إعادة تحميل المعاينة: ${url}`,
      filesChanged: (count, url) =>
        arPlural(count, {
          one: `تغيّر ملف واحد، جارٍ إعادة تحميل المعاينة: ${url}`,
          two: `تغيّر ملفان، جارٍ إعادة تحميل المعاينة: ${url}`,
          few: `تغيّرت ${count} ملفات، جارٍ إعادة تحميل المعاينة: ${url}`,
          many: `تغيّر ${count} ملفًا، جارٍ إعادة تحميل المعاينة: ${url}`,
          other: `تغيّر ${count} ملف، جارٍ إعادة تحميل المعاينة: ${url}`
        }),
      watchFailed: message => `تعذّرت مراقبة ملف المعاينة: ${message}`,
      moduleMimeDescription:
        'تُقدَّم نصوص الوحدات بنوع MIME خاطئ. يعني هذا عادة أن خادم ملفات ثابتة يقدّم تطبيق Vite/React بدلًا من خادم التطوير للمشروع.',
      loadFailedConsole: (code, message) => `فشل التحميل${code ? ` (${code})` : ''}: ${message}`,
      unreachableDescription: 'تعذّر الوصول إلى صفحة المعاينة.',
      openTarget: url => `فتح ${url}`,
      fallbackTitle: 'معاينة'
    }
  },

  assistant: {
    thread: {
      loadingSession: 'جارٍ تحميل الجلسة',
      showEarlier: 'إظهار الرسائل السابقة',
      loadingResponse: 'Simplicio يحمّل ردًا',
      resumeWhenBackgroundDone: count =>
        arPlural(count, {
          one: 'سيُستأنَف عند انتهاء المهمة الخلفية',
          two: 'سيُستأنَف عند انتهاء مهمتين خلفيتين',
          few: `سيُستأنَف عند انتهاء ${count} مهام خلفية`,
          many: `سيُستأنَف عند انتهاء ${count} مهمة خلفية`,
          other: `سيُستأنَف عند انتهاء ${count} مهمة خلفية`
        }),
      thinking: 'يفكر',
      today: time => `اليوم، ${time}`,
      yesterday: time => `أمس، ${time}`,
      copy: 'نسخ',
      refresh: 'تحديث',
      moreActions: 'إجراءات إضافية',
      branchNewChat: 'تفريع في محادثة جديدة',
      dismissError: 'إغلاق الخطأ',
      readAloudFailed: 'فشلت القراءة بصوت عالٍ',
      preparingAudio: 'جارٍ تجهيز الصوت...',
      stopReading: 'إيقاف القراءة',
      readAloud: 'قراءة بصوت عالٍ',
      editMessage: 'تعديل الرسالة',
      expandMessage: 'توسيع الرسالة',
      scrollToBottom: 'التمرير إلى الأسفل',
      stop: 'إيقاف',
      restorePrevious: 'استعادة نقطة الاستعادة السابقة',
      restoreCheckpoint: 'استعادة نقطة الاستعادة',
      restoreFromHere: 'استعادة نقطة الاستعادة — إعادة التشغيل من هذا الموجّه',
      restoreTitle: 'الاستعادة إلى نقطة الاستعادة هذه؟',
      restoreBody: 'تُزال كل الرسائل بعد هذا الموجّه من المحادثة، ويعاد تشغيل الموجّه من هنا.',
      restoreConfirm: 'استعادة وإعادة تشغيل',
      restoreNext: 'استعادة نقطة الاستعادة التالية',
      goForward: 'التقدم للأمام',
      sendEdited: 'إرسال الرسالة المعدَّلة',
      attachingFile: 'جارٍ الإرفاق…'
    },
    approval: {
      gatewayDisconnected: 'بوابة Simplicio غير متصلة',
      sendFailed: 'تعذّر إرسال رد الموافقة',
      run: 'تشغيل',
      command: 'الأمر',
      moreOptions: 'خيارات موافقة إضافية',
      allowSession: 'السماح لهذه الجلسة',
      alwaysAllowMenu: 'السماح دائمًا…',
      jumpToApproval: 'يلزم الموافقة',
      reject: 'رفض',
      alwaysTitle: 'السماح بهذا الأمر دائمًا؟',
      alwaysDescription: pattern =>
        `يضيف هذا نمط "${pattern}" إلى قائمة السماح الدائمة (~/.hermes/config.yaml). لن يسأل Simplicio مرة أخرى عن أوامر مثل هذا — في هذه الجلسة أو أي جلسة مستقبلية.`,
      alwaysAllow: 'السماح دائمًا'
    },
    clarify: {
      notReady: 'طلب التوضيح غير جاهز بعد',
      gatewayDisconnected: 'بوابة Simplicio غير متصلة',
      sendFailed: 'تعذّر إرسال رد التوضيح',
      loadingQuestion: 'جارٍ تحميل السؤال…',
      other: 'أخرى (اكتب إجابتك)',
      placeholder: 'اكتب إجابتك…',
      skip: 'تخطي',
      continueLabel: 'متابعة'
    },
    tool: {
      code: 'الشيفرة',
      copyCode: 'نسخ الشيفرة',
      renderingImage: 'جارٍ عرض الصورة',
      copyOutput: 'نسخ المخرجات',
      copyCommand: 'نسخ الأمر',
      copyContent: 'نسخ المحتوى',
      copyUrl: 'نسخ العنوان',
      copyResults: 'نسخ النتائج',
      copyQuery: 'نسخ الاستعلام',
      copyFile: 'نسخ الملف',
      copyPath: 'نسخ المسار',
      outputAlt: 'مخرجات الأداة',
      rawResponse: 'الرد الخام',
      copyActivity: 'نسخ النشاط',
      recoveredOne: 'تمت الاستعادة بعد خطوة واحدة فاشلة',
      recoveredMany: count =>
        arPlural(count, {
          one: 'تمت الاستعادة بعد خطوة واحدة فاشلة',
          two: 'تمت الاستعادة بعد خطوتين فاشلتين',
          few: `تمت الاستعادة بعد ${count} خطوات فاشلة`,
          many: `تمت الاستعادة بعد ${count} خطوة فاشلة`,
          other: `تمت الاستعادة بعد ${count} خطوة فاشلة`
        }),
      failedOne: 'فشلت خطوة واحدة',
      failedMany: count =>
        arPlural(count, {
          one: 'فشلت خطوة واحدة',
          two: 'فشلت خطوتان',
          few: `فشلت ${count} خطوات`,
          many: `فشلت ${count} خطوة`,
          other: `فشلت ${count} خطوة`
        }),
      statusRunning: 'قيد التشغيل',
      statusError: 'خطأ',
      statusRecovered: 'استُعيدت',
      statusDone: 'تم',
      actions: {
        read: 'قراءة',
        reading: 'جارٍ القراءة',
        opened: 'فُتح',
        opening: 'جارٍ الفتح',
        failedToOpen: 'فشل الفتح',
        searched: 'تم البحث',
        searching: 'جارٍ البحث',
        ran: 'تم التشغيل',
        running: 'جارٍ التشغيل',
        ranCode: 'تم تشغيل الشيفرة',
        runningCode: 'جارٍ البرمجة النصية'
      },
      prefixes: {
        browser: 'المتصفح',
        web: 'الويب'
      },
      titleTemplates: {
        actionCommand: (action, command) => `${action} ${command}`,
        actionQuoted: (action, value) => `${action} "${value}"`,
        actionTarget: (action, target) => `${action} ${target}`,
        prefixedDone: (prefix, action) => `${prefix} ${action}`,
        runningPrefixedTool: (prefix, action) => `جارٍ ${action} ${prefix}`,
        runningTool: action => `جارٍ ${action}`
      },
      titles: {
        browser_click: { done: 'تم النقر على عنصر الصفحة', pending: 'جارٍ النقر على عنصر الصفحة', pendingAction: 'جارٍ النقر' },
        browser_fill: { done: 'تم ملء حقل النموذج', pending: 'جارٍ ملء حقل النموذج', pendingAction: 'جارٍ الملء' },
        browser_navigate: { done: 'تم فتح الصفحة', pending: 'جارٍ فتح الصفحة', pendingAction: 'جارٍ الفتح' },
        browser_snapshot: {
          done: 'تم التقاط لقطة الصفحة',
          pending: 'جارٍ التقاط لقطة الصفحة',
          pendingAction: 'جارٍ الالتقاط'
        },
        browser_take_screenshot: {
          done: 'تم التقاط لقطة الشاشة',
          pending: 'جارٍ التقاط لقطة الشاشة',
          pendingAction: 'جارٍ الالتقاط'
        },
        browser_type: { done: 'تمت الكتابة على الصفحة', pending: 'جارٍ الكتابة على الصفحة', pendingAction: 'جارٍ الكتابة' },
        clarify: { done: 'طُرح سؤال', pending: 'جارٍ طرح سؤال', pendingAction: 'جارٍ السؤال' },
        computer_use: { done: 'تم التحكم في سطح المكتب', pending: 'جارٍ التحكم في سطح المكتب', pendingAction: 'جارٍ التحكم' },
        cronjob: { done: 'مهمة مجدولة', pending: 'جارٍ جدولة مهمة', pendingAction: 'جارٍ الجدولة' },
        edit_file: { done: 'تم تعديل الملف', pending: 'جارٍ تعديل الملف', pendingAction: 'جارٍ التعديل' },
        execute_code: { done: 'تم تشغيل الشيفرة', pending: 'جارٍ البرمجة النصية', pendingAction: 'جارٍ البرمجة النصية' },
        image_generate: { done: 'تم توليد الصورة', pending: 'جارٍ توليد الصورة', pendingAction: 'جارٍ التوليد' },
        list_files: { done: 'تم سرد الملفات', pending: 'جارٍ سرد الملفات', pendingAction: 'جارٍ السرد' },
        patch: { done: 'تم تصحيح الملف', pending: 'جارٍ تصحيح الملف', pendingAction: 'جارٍ التصحيح' },
        read_file: { done: 'تمت قراءة الملف', pending: 'جارٍ قراءة الملف', pendingAction: 'جارٍ القراءة' },
        search_files: { done: 'تم البحث في الملفات', pending: 'جارٍ البحث في الملفات', pendingAction: 'جارٍ البحث' },
        session_search_recall: {
          done: 'تم البحث في سجل الجلسة',
          pending: 'جارٍ البحث في سجل الجلسة',
          pendingAction: 'جارٍ البحث'
        },
        terminal: { done: 'تم تشغيل الأمر', pending: 'جارٍ تشغيل الأمر', pendingAction: 'جارٍ التشغيل' },
        todo: { done: 'تم تحديث المهام', pending: 'جارٍ تحديث المهام', pendingAction: 'جارٍ التحديث' },
        vision_analyze: { done: 'تم تحليل الصورة', pending: 'جارٍ تحليل الصورة', pendingAction: 'جارٍ التحليل' },
        web_extract: { done: 'تمت قراءة صفحة الويب', pending: 'جارٍ قراءة صفحة الويب', pendingAction: 'جارٍ القراءة' },
        web_search: { done: 'تم البحث في الويب', pending: 'جارٍ البحث في الويب', pendingAction: 'جارٍ البحث' },
        write_file: { done: 'تم تعديل الملف', pending: 'جارٍ تعديل الملف', pendingAction: 'جارٍ التعديل' }
      }
    }
  },

  prompts: {
    gatewayDisconnected: 'بوابة Simplicio غير متصلة',
    sudoSendFailed: 'تعذّر إرسال كلمة مرور sudo',
    secretSendFailed: 'تعذّر إرسال السرّ',
    sudoTitle: 'كلمة مرور المسؤول',
    sudoDesc: 'يحتاج Simplicio إلى كلمة مرور sudo لتشغيل أمر بامتياز. تُرسَل فقط إلى وكيلك المحلي.',
    sudoPlaceholder: 'كلمة مرور sudo',
    secretTitle: 'مطلوب سرّ',
    secretDesc: 'يحتاج Simplicio إلى بيانات اعتماد للمتابعة.',
    secretPlaceholder: 'قيمة السرّ'
  },

  desktop: {
    audioReadFailed: 'تعذّرت قراءة الصوت المسجَّل',
    sessionUnavailable: 'الجلسة غير متاحة',
    createSessionFailed: 'تعذّر إنشاء جلسة جديدة',
    promptFailed: 'فشل الموجّه',
    providerCredentialRequired: 'أضف بيانات اعتماد مزوّد قبل إرسال رسالتك الأولى.',
    emptySlashCommand: 'أمر شرطة مائلة فارغ',
    desktopCommands: 'أوامر سطح المكتب',
    skillCommandsAvailable: count =>
      arPlural(count, {
        one: 'يتوفر أمر مهارة واحد.',
        two: 'يتوفر أمرا مهارة.',
        few: `تتوفر ${count} أوامر مهارات.`,
        many: `يتوفر ${count} أمر مهارة.`,
        other: `يتوفر ${count} أمر مهارة.`
      }),
    warningLine: message => `تحذير: ${message}`,
    yoloArmed: 'YOLO مفعَّل لهذه المحادثة',
    yoloOff: 'YOLO معطَّل',
    yoloSystem: active => `YOLO ${active ? 'مفعَّل' : 'معطَّل'} لهذه الجلسة`,
    yoloTitle: 'YOLO',
    yoloToggleFailed: 'تعذّر تبديل YOLO',
    profileStatus: current =>
      `الملف الشخصي: ${current}. استخدم ‎/profile <name>‎ أو مُنتقي "جلسة جديدة" لبدء محادثة في ملف شخصي آخر.`,
    unknownProfile: 'ملف شخصي غير معروف',
    noProfileNamed: (target, available) => `لا يوجد ملف شخصي باسم "${target}". المتاح: ${available}`,
    newChatsProfile: name => `ستستخدم المحادثات الجديدة الملف الشخصي ${name}.`,
    setProfileFailed: 'فشل تعيين الملف الشخصي',
    sttDisabled: 'تحويل الكلام إلى نص معطَّل في الإعدادات.',
    stopFailed: 'فشل الإيقاف',
    regenerateFailed: 'فشلت إعادة التوليد',
    editFailed: 'فشل التعديل',
    resumeFailed: 'فشل الاستئناف',
    resumeStrandedTitle: 'تعذّر تحميل هذه الجلسة',
    resumeStrandedBody: 'فشل الاتصال بهذه الجلسة وتخلّت المحاولات التلقائية. تحقق من أن البوابة تعمل، ثم أعد المحاولة.',
    resumeRetry: 'إعادة المحاولة',
    nothingToBranch: 'لا شيء للتفريع',
    branchNeedsChat: 'ابدأ أو استأنف محادثة قبل التفريع.',
    sessionBusy: 'الجلسة مشغولة',
    branchStopCurrent: 'أوقف الجولة الحالية قبل تفريع هذه المحادثة.',
    branchNoText: 'لا تحتوي هذه الرسالة على نص للتفريع منه.',
    branchTitle: n => `مسودة: التفريع #${n}`,
    branchFailed: 'فشل التفريع',
    deleteFailed: 'فشل الحذف',
    archived: 'أُرشِفت',
    archiveFailed: 'فشلت الأرشفة',
    cwdChangeFailed: 'فشل تغيير مجلد العمل',
    cwdStagedTitle: 'تم تجهيز مجلد العمل',
    cwdStagedMessage: 'أعد تشغيل الخادم الخلفي لسطح المكتب لتطبيق تغييرات مجلد العمل على هذه الجلسة النشطة.',
    modelSwitchFailed: 'فشل تبديل النموذج',
    sessionExported: 'تم تصدير الجلسة',
    sessionExportFailed: 'تعذّر تصدير الجلسة',
    imageSaved: 'تم حفظ الصورة',
    downloadStarted: 'بدأ التنزيل',
    restartToUseSaveImage: 'أعد تشغيل Simplicio Desktop لاستخدام حفظ الصورة.',
    restartToSaveImages: 'أعد تشغيل Simplicio Desktop لحفظ الصور',
    imageDownloadFailed: 'فشل تنزيل الصورة',
    openImage: 'فتح الصورة',
    downloadImage: 'تنزيل الصورة',
    savingImage: 'جارٍ حفظ الصورة',
    imagePreviewFailed: 'فشلت معاينة الصورة',
    imageAttach: 'إرفاق صورة',
    imageWriteFailed: 'فشلت كتابة الصورة على القرص.',
    imageAttachFailed: 'فشل إرفاق الصورة',
    attachImages: 'إرفاق صور',
    clipboard: 'الحافظة',
    noClipboardImage: 'لم يُعثر على صورة في الحافظة',
    clipboardPasteFailed: 'فشل لصق الحافظة',
    dropFiles: 'إفلات الملفات',
    handoff: {
      pickPlatform: 'اختر وجهة',
      success: platform => `تم التسليم إلى ${platform}. استأنف هنا في أي وقت.`,
      systemNote: platform => `↻ تم التسليم إلى ${platform} — استأنف هنا في أي وقت.`,
      failed: error => `فشل التسليم: ${error}`,
      timedOut: 'انتهت مهلة انتظار البوابة. هل يعمل `hermes gateway`؟'
    }
  },

  errors: {
    genericFailure: 'حدث خطأ ما',
    boundaryTitle: 'واجه Simplicio Agent خطأ غير متوقع',
    boundaryDesc: 'محادثاتك وإعداداتك آمنة. أعد تحميل النافذة للمتابعة.',
    reloadWindow: 'إعادة تحميل النافذة',
    openLogs: 'فتح السجلات'
  },

  ui: {
    search: {
      clear: 'مسح البحث'
    },
    pagination: {
      label: 'ترقيم الصفحات',
      previous: 'السابق',
      previousAria: 'الانتقال إلى الصفحة السابقة',
      next: 'التالي',
      nextAria: 'الانتقال إلى الصفحة التالية'
    },
    sidebar: {
      title: 'الشريط الجانبي',
      description: 'يعرض الشريط الجانبي على الجوال.',
      toggle: 'تبديل الشريط الجانبي'
    }
  }
})
