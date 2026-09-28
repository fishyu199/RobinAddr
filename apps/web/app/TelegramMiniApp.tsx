'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';

type Insets = { top?: number; right?: number; bottom?: number; left?: number };
type TelegramBackButton = {
  show: () => TelegramBackButton;
  hide: () => TelegramBackButton;
  onClick: (callback: () => void) => TelegramBackButton;
  offClick: (callback: () => void) => TelegramBackButton;
};
type TelegramWebApp = {
  initData?: string;
  platform?: string;
  colorScheme?: 'light' | 'dark';
  viewportHeight?: number;
  viewportStableHeight?: number;
  safeAreaInset?: Insets;
  contentSafeAreaInset?: Insets;
  themeParams?: Record<string, string | undefined>;
  BackButton?: TelegramBackButton;
  ready: () => void;
  expand: () => void;
  disableVerticalSwipes?: () => void;
  enableVerticalSwipes?: () => void;
  isVersionAtLeast?: (version: string) => boolean;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  openLink?: (url: string) => void;
  openTelegramLink?: (url: string) => void;
  onEvent?: (event: string, callback: (...args: unknown[]) => void) => void;
  offEvent?: (event: string, callback: (...args: unknown[]) => void) => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const px = (value?: number) => `${Math.max(0, Number(value) || 0)}px`;

function isTelegramLaunch(webApp: TelegramWebApp) {
  const params = new URLSearchParams(window.location.search);
  return Boolean(
    webApp.initData
    || params.has('tgWebAppVersion')
    || params.has('tgWebAppPlatform')
    || (webApp.platform && webApp.platform !== 'unknown'),
  );
}

function applyTelegramEnvironment(webApp: TelegramWebApp) {
  const root = document.documentElement;
  const safe = webApp.safeAreaInset ?? {};
  const contentSafe = webApp.contentSafeAreaInset ?? {};

  root.dataset.telegramMiniApp = 'true';
  root.dataset.telegramColorScheme = webApp.colorScheme ?? 'dark';

  if (webApp.viewportHeight) root.style.setProperty('--tg-viewport-height', px(webApp.viewportHeight));
  if (webApp.viewportStableHeight) root.style.setProperty('--tg-viewport-stable-height', px(webApp.viewportStableHeight));

  for (const edge of ['top', 'right', 'bottom', 'left'] as const) {
    root.style.setProperty(`--tg-safe-area-inset-${edge}`, px(safe[edge]));
    root.style.setProperty(`--tg-content-safe-area-inset-${edge}`, px(contentSafe[edge]));
  }
}

function setTelegramChrome(webApp: TelegramWebApp, isPublicPage: boolean) {
  const background = isPublicPage ? '#000000' : (webApp.themeParams?.bg_color ?? '#ffffff');
  try { webApp.setHeaderColor?.(background); } catch { /* Older clients reject custom colors. */ }
  try { webApp.setBackgroundColor?.(background); } catch { /* Capability checked at runtime. */ }
  if (webApp.isVersionAtLeast?.('7.10')) {
    try { webApp.setBottomBarColor?.(background); } catch { /* Capability checked at runtime. */ }
  }
}

export default function TelegramMiniApp() {
  const pathname = usePathname();
  const router = useRouter();
  const [telegramReady, setTelegramReady] = useState(false);

  useEffect(() => {
    let disposed = false;
    let attempts = 0;
    let cleanup = () => {};
    const launchParams = new URLSearchParams(window.location.search);
    const mayBeTelegram = Boolean(
      window.Telegram?.WebApp
      || launchParams.has('tgWebAppData')
      || launchParams.has('tgWebAppVersion')
      || launchParams.has('tgWebAppPlatform'),
    );
    if (!mayBeTelegram) return;

    const initialize = () => {
      const webApp = window.Telegram?.WebApp;
      if (!webApp || !isTelegramLaunch(webApp)) {
        if (!disposed && attempts++ < 40) window.setTimeout(initialize, 50);
        return;
      }

      const syncEnvironment = () => {
        applyTelegramEnvironment(webApp);
        setTelegramChrome(webApp, !window.location.pathname.startsWith('/admin'));
      };
      const handleLink = (event: MouseEvent) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
        if (!(target instanceof HTMLAnchorElement)) return;

        const url = new URL(target.href, window.location.href);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
        if ((url.hostname === 't.me' || url.hostname === 'telegram.me') && webApp.openTelegramLink) {
          event.preventDefault();
          webApp.openTelegramLink(url.toString());
          return;
        }
        if (url.origin !== window.location.origin && target.target === '_blank' && webApp.openLink) {
          event.preventDefault();
          webApp.openLink(url.toString());
        }
      };

      syncEnvironment();
      webApp.onEvent?.('viewportChanged', syncEnvironment);
      webApp.onEvent?.('themeChanged', syncEnvironment);
      webApp.onEvent?.('safeAreaChanged', syncEnvironment);
      webApp.onEvent?.('contentSafeAreaChanged', syncEnvironment);
      document.addEventListener('click', handleLink, true);
      if (webApp.isVersionAtLeast?.('7.7')) {
        try { webApp.disableVerticalSwipes?.(); } catch { /* Older clients keep their default gesture. */ }
      }
      webApp.expand();
      webApp.ready();
      if (!disposed) setTelegramReady(true);

      cleanup = () => {
        webApp.offEvent?.('viewportChanged', syncEnvironment);
        webApp.offEvent?.('themeChanged', syncEnvironment);
        webApp.offEvent?.('safeAreaChanged', syncEnvironment);
        webApp.offEvent?.('contentSafeAreaChanged', syncEnvironment);
        document.removeEventListener('click', handleLink, true);
        if (webApp.isVersionAtLeast?.('7.7')) {
          try { webApp.enableVerticalSwipes?.(); } catch { /* The Mini App may already be closing. */ }
        }
      };
    };

    if (window.Telegram?.WebApp) {
      initialize();
    } else {
      const script = document.createElement('script');
      script.src = 'https://telegram.org/js/telegram-web-app.js?63';
      script.async = true;
      script.onload = initialize;
      document.head.appendChild(script);
    }
    return () => {
      disposed = true;
      cleanup();
    };
  }, []);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    if (!webApp || !isTelegramLaunch(webApp) || !webApp.BackButton) return;

    setTelegramChrome(webApp, !pathname.startsWith('/admin'));
    if (pathname === '/') {
      webApp.BackButton.hide();
      return;
    }

    const handleBack = () => {
      let hasSameOriginReferrer = false;
      try {
        hasSameOriginReferrer = Boolean(document.referrer && new URL(document.referrer).origin === window.location.origin);
      } catch {
        hasSameOriginReferrer = false;
      }

      if (hasSameOriginReferrer && window.history.length > 1) router.back();
      else router.replace('/');
    };

    webApp.BackButton.onClick(handleBack);
    webApp.BackButton.show();
    return () => {
      webApp.BackButton?.offClick(handleBack);
      webApp.BackButton?.hide();
    };
  }, [pathname, router, telegramReady]);

  return null;
}
