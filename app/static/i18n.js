/* Feishu↔Outlook portal: language + theme */
(function () {
  const ZH_TZ = new Set([
    "Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi",
    "Asia/Hong_Kong", "Asia/Macau", "Asia/Taipei", "Asia/Beijing"
  ]);

  const I18N = {
    zh: {
      "doc.title": "飞书 ↔ Outlook 同步",
      "brand.title": "飞书 ↔ Outlook 日历同步",
      "brand.sub": "每人独立授权 · 可选同步方向 · 防回环专用日历",
      "pill.outlook": "个人 Outlook.com",
      "pill.feishu": "飞书 Open API",
      "footer": "同步窗口与间隔由管理员配置。问题请联系部署负责人。",
      "footer.credit": "feishu-outlook-sync-oss · MIT",
      "ctrl.lang": "语言",
      "ctrl.theme": "外观",
      "ctrl.lang.auto": "自动",
      "ctrl.lang.zh": "中文",
      "ctrl.lang.en": "English",
      "ctrl.theme.auto": "日出",
      "ctrl.theme.light": "浅色",
      "ctrl.theme.dark": "深色",
      "step.connect": "连接账户",
      "step.direction": "同步方向",
      "step.sync": "同步执行",
      "step.n1": "步骤 1",
      "step.n2": "步骤 2",
      "step.n3": "步骤 3",
      "user.current": "当前用户：",
      "user.logout": "退出会话",
      "welcome.title": "尚未登录",
      "user.empty": "先连接 Outlook 或飞书，连接成功后会自动建立本站会话。",
      "theme.tip.auto": "外观：按日出日落自动",
      "theme.tip.light": "外观：浅色",
      "theme.tip.dark": "外观：深色",
      "feishu.name": "飞书",
      "outlook.name": "Outlook.com",
      "badge.on": "已连接",
      "badge.off": "未连接",
      "feishu.meta.off": "授权后可读 / 写日历",
      "outlook.meta.off": "个人 Microsoft 账户",
      "btn.connect.feishu": "连接飞书",
      "btn.connect.outlook": "连接 Outlook",
      "btn.disconnect": "断开",
      "map.title": "防回环说明",
      "map.intro": "写入的目标日历不会再被当作源拉取。",
      "map.f2o": "飞书 → Outlook：源 = 飞书主日历 → 目标 = Outlook「{outlook}」",
      "map.o2f": "Outlook → 飞书：源 = Outlook默认日历 → 目标 = 飞书「{feishu}」",
      "map.skip_sub": "飞书「订阅」日历默认不同步到 Outlook（仅主日历）",
      "dir.f2o.title": "飞书 → Outlook",
      "dir.f2o.desc": "飞书主日历写入 Outlook「{outlook}」（推荐默认）",
      "dir.o2f.title": "Outlook → 飞书",
      "dir.o2f.desc": "Outlook 默认日历写入飞书「{feishu}」",
      "dir.bi.title": "双向同步",
      "dir.bi.desc": "两腿都跑；各自写入独立目标日历，避免回环",
      "warn.write": "当前方向需要飞书日历写权限。若升级前只用只读权限连过飞书，请先断开再重新连接，以授权 calendar:calendar。",
      "btn.save.dir": "保存同步方向",
      "stat.dir": "当前方向",
      "stat.last": "最近同步",
      "stat.status": "状态",
      "dir.label.f2o": "飞书 → Outlook",
      "dir.label.o2f": "Outlook → 飞书",
      "dir.label.bi": "双向",
      "sync.never": "尚未同步",
      "sync.interval": "自动同步间隔约 {n} 分钟（两端已连接且开启自动同步时）。",
      "btn.sync.now": "立即同步",
      "btn.auto.off": "关闭自动同步",
      "btn.auto.on": "开启自动同步",
      "sync.need.login": "连接账户后即可手动或自动同步。",
      "help.title": "使用说明",
      "help.expand": "展开",
      "help.collapse": "收起",
      "help.1": "连接 Outlook（个人 Microsoft 账户）并授权日历读写。",
      "help.2": "连接飞书并授权日历（读 + 写；Outlook→飞书 / 双向时需要写权限）。",
      "help.3": "选择同步方向并保存。",
      "help.4": "点击「立即同步」，或等待定时任务。",
      "help.4a": "飞书 → Outlook：主日历 →「{outlook}」（订阅日历默认跳过）",
      "help.4b": "Outlook → 飞书：默认日历 →「{feishu}」",
      "help.4c": "双向：两腿都跑，目标日历互不作为源",
      "help.5": "请勿在目标日历里改日程；请在对应源日历中修改。"
    },
    en: {
      "doc.title": "Feishu ↔ Outlook Sync",
      "brand.title": "Feishu ↔ Outlook Calendar Sync",
      "brand.sub": "Per-user OAuth · Choose direction · Loop-safe target calendars",
      "pill.outlook": "Personal Outlook.com",
      "pill.feishu": "Feishu Open API",
      "footer": "Sync window and interval are set by the admin. Contact your deployer for help.",
      "footer.credit": "feishu-outlook-sync-oss · MIT",
      "ctrl.lang": "Language",
      "ctrl.theme": "Theme",
      "ctrl.lang.auto": "Auto",
      "ctrl.lang.zh": "中文",
      "ctrl.lang.en": "English",
      "ctrl.theme.auto": "Sunrise",
      "ctrl.theme.light": "Light",
      "ctrl.theme.dark": "Dark",
      "step.connect": "Connect accounts",
      "step.direction": "Sync direction",
      "step.sync": "Run sync",
      "step.n1": "Step 1",
      "step.n2": "Step 2",
      "step.n3": "Step 3",
      "user.current": "Signed in as ",
      "user.logout": "Sign out",
      "welcome.title": "Not signed in",
      "user.empty": "Connect Outlook or Feishu first; a session is created after you authorize.",
      "theme.tip.auto": "Theme: auto by sunrise/sunset",
      "theme.tip.light": "Theme: light",
      "theme.tip.dark": "Theme: dark",
      "feishu.name": "Feishu",
      "outlook.name": "Outlook.com",
      "badge.on": "Connected",
      "badge.off": "Not connected",
      "feishu.meta.off": "Authorize calendar read / write",
      "outlook.meta.off": "Personal Microsoft account",
      "btn.connect.feishu": "Connect Feishu",
      "btn.connect.outlook": "Connect Outlook",
      "btn.disconnect": "Disconnect",
      "map.title": "Anti-loop",
      "map.intro": "Target calendars written by sync are never used as sources.",
      "map.f2o": "Feishu → Outlook: source = Feishu primary → target = Outlook “{outlook}”",
      "map.o2f": "Outlook → Feishu: source = Outlook default → target = Feishu “{feishu}”",
      "map.skip_sub": "Feishu subscribed calendars are skipped by default (primary only)",
      "dir.f2o.title": "Feishu → Outlook",
      "dir.f2o.desc": "Feishu primary → Outlook “{outlook}” (recommended default)",
      "dir.o2f.title": "Outlook → Feishu",
      "dir.o2f.desc": "Outlook default → Feishu “{feishu}”",
      "dir.bi.title": "Bidirectional",
      "dir.bi.desc": "Both legs; each writes its own target calendar to avoid loops",
      "warn.write": "This direction needs Feishu calendar write scope. If you connected with read-only before, disconnect and reconnect to grant calendar:calendar.",
      "btn.save.dir": "Save direction",
      "stat.dir": "Direction",
      "stat.last": "Last sync",
      "stat.status": "Status",
      "dir.label.f2o": "Feishu → Outlook",
      "dir.label.o2f": "Outlook → Feishu",
      "dir.label.bi": "Bidirectional",
      "sync.never": "Never synced",
      "sync.interval": "Auto-sync about every {n} minutes when both sides are connected and auto-sync is on.",
      "btn.sync.now": "Sync now",
      "btn.auto.off": "Turn off auto-sync",
      "btn.auto.on": "Turn on auto-sync",
      "sync.need.login": "Connect accounts to sync manually or on a schedule.",
      "help.title": "How to use",
      "help.expand": "Expand",
      "help.collapse": "Collapse",
      "help.1": "Connect Outlook (personal Microsoft account) and grant calendar read/write.",
      "help.2": "Connect Feishu and grant calendar access (read + write; write is required for Outlook→Feishu / bidirectional).",
      "help.3": "Choose a sync direction and save.",
      "help.4": "Click “Sync now”, or wait for the scheduler.",
      "help.4a": "Feishu → Outlook: primary → “{outlook}” (subscribed calendars skipped by default)",
      "help.4b": "Outlook → Feishu: default → “{feishu}”",
      "help.4c": "Bidirectional: both legs; targets are never sources",
      "help.5": "Don’t edit events in target calendars; change them in the source calendars."
    }
  };

  const FLASH_MAP = {
    "服务未配置 MS_CLIENT_ID": "MS_CLIENT_ID is not configured",
    "Microsoft OAuth state 无效，请重试": "Microsoft OAuth state invalid — try again",
    "已断开 Outlook 连接": "Outlook disconnected",
    "服务未配置 FEISHU_APP_ID": "FEISHU_APP_ID is not configured",
    "飞书 OAuth state 无效，请重试": "Feishu OAuth state invalid — try again",
    "已断开飞书连接": "Feishu disconnected",
    "已退出本地会话": "Signed out of local session",
    "请先连接账户": "Connect an account first",
    "会话无效": "Invalid session",
    "未登录": "Not signed in",
    "已更新自动同步设置": "Auto-sync setting updated",
    "无效的同步方向": "Invalid sync direction",
    "用户不存在": "User not found",
    "尚未同步": "Never synced"
  };

  function detectLangFromBrowserAndSystem() {
    // Prefer browser / OS UI languages, then timezone as Chinese-region hint.
    try {
      const list = [];
      if (navigator.languages && navigator.languages.length) {
        for (let i = 0; i < navigator.languages.length; i++) list.push(navigator.languages[i]);
      }
      if (navigator.language) list.push(navigator.language);
      if (navigator.userLanguage) list.push(navigator.userLanguage);
      for (let i = 0; i < list.length; i++) {
        const nav = String(list[i] || "").toLowerCase();
        if (nav.startsWith("zh")) return "zh";
      }
      // If any browser lang is clearly English-first and none zh, prefer en
      for (let i = 0; i < list.length; i++) {
        const nav = String(list[i] || "").toLowerCase();
        if (nav.startsWith("en")) return "en";
      }
    } catch (e) {}
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      if (ZH_TZ.has(tz) || /Shanghai|Chongqing|Harbin|Urumqi|Hong_Kong|Macau|Taipei|Beijing/i.test(tz)) {
        return "zh";
      }
    } catch (e2) {}
    return "en";
  }

  function approxLatLonFromTimezone(tz) {
    // Rough city centers for sunrise calc when geolocation is unavailable.
    const map = {
      "Asia/Shanghai": [31.23, 121.47],
      "Asia/Chongqing": [29.56, 106.55],
      "Asia/Harbin": [45.75, 126.65],
      "Asia/Urumqi": [43.83, 87.62],
      "Asia/Hong_Kong": [22.32, 114.17],
      "Asia/Macau": [22.20, 113.54],
      "Asia/Taipei": [25.03, 121.57],
      "Asia/Beijing": [39.90, 116.40],
      "Asia/Singapore": [1.35, 103.82],
      "Asia/Tokyo": [35.68, 139.69],
      "America/Los_Angeles": [34.05, -118.24],
      "America/New_York": [40.71, -74.01],
      "Europe/London": [51.51, -0.13]
    };
    if (map[tz]) return map[tz];
    if (/Asia\//.test(tz)) return [31.23, 121.47];
    return [31.23, 121.47]; // default Shanghai / CN
  }

  function solarElevationTimes(date, lat, lon) {
    // Returns { sunrise: Date, sunset: Date } using NOAA-ish approximation (local).
    const rad = Math.PI / 180;
    const day = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate(), 12, 0, 0));
    const n = Math.floor((day - Date.UTC(date.getFullYear(), 0, 0)) / 86400000);
    const lngHour = lon / 15;
    function event(isRise) {
      const t = n + ((isRise ? 6 : 18) - lngHour) / 24;
      const M = (0.9856 * t) - 3.289;
      let L = M + (1.916 * Math.sin(M * rad)) + (0.020 * Math.sin(2 * M * rad)) + 282.634;
      L = ((L % 360) + 360) % 360;
      let RA = Math.atan(0.91764 * Math.tan(L * rad)) / rad;
      RA = ((RA % 360) + 360) % 360;
      const Lquadrant = Math.floor(L / 90) * 90;
      const RAquadrant = Math.floor(RA / 90) * 90;
      RA = RA + (Lquadrant - RAquadrant);
      RA = RA / 15;
      const sinDec = 0.39782 * Math.sin(L * rad);
      const cosDec = Math.cos(Math.asin(sinDec));
      const cosH = (Math.cos(90.833 * rad) - (sinDec * Math.sin(lat * rad))) / (cosDec * Math.cos(lat * rad));
      if (cosH > 1) return null; // polar night-ish
      if (cosH < -1) return null; // polar day-ish
      let H = isRise ? (360 - Math.acos(cosH) / rad) : (Math.acos(cosH) / rad);
      H = H / 15;
      const T = H + RA - (0.06571 * t) - 6.622;
      let UT = T - lngHour;
      UT = ((UT % 24) + 24) % 24;
      const out = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0));
      out.setUTCMinutes(Math.round(UT * 60));
      return out;
    }
    return { sunrise: event(true), sunset: event(false) };
  }

  var _geoCoords = null;
  function ensureGeoCoords() {
    if (_geoCoords !== null) return;
    _geoCoords = false;
    if (!navigator.geolocation) return;
    try {
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          _geoCoords = [pos.coords.latitude, pos.coords.longitude];
          if (getThemePref() === "auto") applyI18n();
        },
        function () { _geoCoords = false; },
        { maximumAge: 86400000, timeout: 4000 }
      );
    } catch (e) {}
  }

  function detectThemeFromSunrise() {
    try {
      const now = new Date();
      let latlon;
      if (_geoCoords && _geoCoords.length === 2) latlon = _geoCoords;
      else {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
        latlon = approxLatLonFromTimezone(tz);
      }
      const times = solarElevationTimes(now, latlon[0], latlon[1]);
      if (!times.sunrise || !times.sunset) {
        // fallback: 6:30–18:30 local
        const h = now.getHours() + now.getMinutes() / 60;
        return (h >= 6.5 && h < 18.5) ? "light" : "dark";
      }
      // Daytime = after sunrise and before sunset
      if (now >= times.sunrise && now < times.sunset) return "light";
      return "dark";
    } catch (e) {
      return "dark";
    }
  }

  function getLangPref() {
    return localStorage.getItem("fos_lang") || "auto";
  }
  function getThemePref() {
    return localStorage.getItem("fos_theme") || "auto";
  }
  function resolveLang() {
    const pref = getLangPref();
    if (pref === "zh" || pref === "en") return pref;
    return detectLangFromBrowserAndSystem();
  }
  function resolveTheme() {
    const pref = getThemePref();
    if (pref === "light" || pref === "dark") return pref;
    return detectThemeFromSunrise();
  }

  function t(key, vars) {
    const lang = document.documentElement.getAttribute("data-lang") || "zh";
    let s = (I18N[lang] && I18N[lang][key]) || (I18N.zh[key]) || key;
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        s = s.replace(new RegExp("\\{" + k + "\\}", "g"), vars[k]);
      });
    }
    return s;
  }

  function applyI18n() {
    const lang = resolveLang();
    const theme = resolveTheme();
    const root = document.documentElement;
    root.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
    root.setAttribute("data-lang", lang);
    root.setAttribute("data-theme", theme);

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#e8eef7" : "#0b1220");

    const vars = {
      outlook: document.body.getAttribute("data-outlook-cal") || "Feishu Sync",
      feishu: document.body.getAttribute("data-feishu-cal") || "Outlook Sync",
      n: document.body.getAttribute("data-sync-interval") || "15"
    };

    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const attr = el.getAttribute("data-i18n-attr");
      const text = t(key, vars);
      if (attr) el.setAttribute(attr, text);
      else el.textContent = text;
    });

    document.querySelectorAll("[data-i18n-html]").forEach(function (el) {
      const key = el.getAttribute("data-i18n-html");
      el.innerHTML = t(key, vars);
    });

    // Direction label that depends on current selection value
    document.querySelectorAll("[data-i18n-dir]").forEach(function (el) {
      const d = el.getAttribute("data-i18n-dir");
      if (d === "outlook_to_feishu") el.textContent = t("dir.label.o2f");
      else if (d === "bidirectional") el.textContent = t("dir.label.bi");
      else el.textContent = t("dir.label.f2o");
    });

    // Help expand/collapse via CSS content from data attrs
    root.style.setProperty("--help-expand", JSON.stringify(t("help.expand")));
    root.style.setProperty("--help-collapse", JSON.stringify(t("help.collapse")));

    document.title = t("doc.title");

    // Flash: translate known Chinese server messages when UI is English
    const flash = document.querySelector(".flash[data-flash-raw]");
    if (flash && lang === "en") {
      const raw = flash.getAttribute("data-flash-raw") || flash.textContent || "";
      let out = raw;
      Object.keys(FLASH_MAP).forEach(function (zh) {
        if (out.indexOf(zh) !== -1) out = out.split(zh).join(FLASH_MAP[zh]);
      });
      // prefixes
      out = out.replace(/^已连接 Outlook：/, "Connected Outlook: ");
      out = out.replace(/^已连接飞书：/, "Connected Feishu: ");
      out = out.replace(/^同步完成：/, "Sync finished: ");
      out = out.replace(/^已保存同步方向：/, "Saved sync direction: ");
      out = out.replace(/无法启动 Microsoft 授权:/, "Cannot start Microsoft auth:");
      out = out.replace(/Microsoft 授权失败:/, "Microsoft auth failed:");
      out = out.replace(/无法启动飞书授权:/, "Cannot start Feishu auth:");
      out = out.replace(/飞书授权失败:/, "Feishu auth failed:");
      out = out.replace(/未连接飞书/g, "Feishu not connected");
      out = out.replace(/未连接 Outlook/g, "Outlook not connected");
      flash.textContent = out;
    }

    syncControlsUI();
  }

  function syncControlsUI() {
    const langPref = getLangPref();
    const themePref = getThemePref();
    const labelKey = langPref === "zh" ? "ctrl.lang.zh" : (langPref === "en" ? "ctrl.lang.en" : "ctrl.lang.auto");
    const cur = document.getElementById("langCurrent");
    if (cur) cur.textContent = t(labelKey);

    document.querySelectorAll("[data-set-lang]").forEach(function (el) {
      const on = el.getAttribute("data-set-lang") === langPref;
      el.classList.toggle("active", on);
      if (el.hasAttribute("role")) el.setAttribute("aria-selected", on ? "true" : "false");
    });

    const themeBtn = document.getElementById("themeBtn");
    if (themeBtn) {
      themeBtn.setAttribute("data-theme-pref", themePref);
      themeBtn.title = t("theme.tip." + themePref);
      themeBtn.setAttribute("aria-label", t("theme.tip." + themePref));
    }
  }

  function closeLangMenu() {
    const menu = document.getElementById("langMenu");
    const trigger = document.getElementById("langTrigger");
    const dd = document.getElementById("langDd");
    if (menu) menu.hidden = true;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (dd) dd.classList.remove("open");
  }

  function bindControls() {
    const trigger = document.getElementById("langTrigger");
    const menu = document.getElementById("langMenu");
    const dd = document.getElementById("langDd");
    if (trigger && menu) {
      trigger.addEventListener("click", function (e) {
        e.stopPropagation();
        const open = menu.hidden;
        menu.hidden = !open;
        trigger.setAttribute("aria-expanded", open ? "true" : "false");
        if (dd) dd.classList.toggle("open", open);
      });
      menu.querySelectorAll("[data-set-lang]").forEach(function (item) {
        item.addEventListener("click", function (e) {
          e.stopPropagation();
          localStorage.setItem("fos_lang", item.getAttribute("data-set-lang"));
          closeLangMenu();
          applyI18n();
        });
      });
      document.addEventListener("click", function () { closeLangMenu(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeLangMenu();
      });
    }

    const themeBtn = document.getElementById("themeBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        const order = ["auto", "light", "dark"];
        const cur = getThemePref();
        const next = order[(order.indexOf(cur) + 1) % order.length];
        localStorage.setItem("fos_theme", next);
        applyI18n();
      });
    }

    // Re-evaluate sunrise/sunset theme periodically while on Auto
    setInterval(function () {
      if (getThemePref() === "auto") applyI18n();
    }, 60 * 1000);
  }

  // Apply theme ASAP to avoid flash (lang can wait for DOM)
  (function earlyTheme() {
    try {
      const pref = localStorage.getItem("fos_theme") || "auto";
      let theme = "dark";
      if (pref === "light" || pref === "dark") theme = pref;
      else {
        // cheap early guess before full sunrise fn is used on DOMContentLoaded
        const h = new Date().getHours() + new Date().getMinutes() / 60;
        theme = (h >= 6.5 && h < 18.5) ? "light" : "dark";
      }
      document.documentElement.setAttribute("data-theme", theme);
      const langPref = localStorage.getItem("fos_lang") || "auto";
      let lang = "zh";
      if (langPref === "en" || langPref === "zh") lang = langPref;
      else {
        try {
          const list = (navigator.languages || []).concat([navigator.language || ""]);
          let hit = null;
          for (let i = 0; i < list.length; i++) {
            const n = String(list[i] || "").toLowerCase();
            if (n.startsWith("zh")) { hit = "zh"; break; }
            if (n.startsWith("en") && !hit) hit = "en";
          }
          if (hit) lang = hit;
          else {
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
            lang = (ZH_TZ.has(tz) || /Shanghai|Chongqing|Harbin|Urumqi|Hong_Kong|Macau|Taipei|Beijing/i.test(tz)) ? "zh" : "en";
          }
        } catch (e2) { lang = "zh"; }
      }
      document.documentElement.setAttribute("data-lang", lang);
      document.documentElement.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
    } catch (e) {}
  })();

  document.addEventListener("DOMContentLoaded", function () {
    ensureGeoCoords();
    bindControls();
    applyI18n();
  });

  window.FOS_UI = { applyI18n: applyI18n, t: t, resolveLang: resolveLang };
})();
