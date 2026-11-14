import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BellRing, Loader2, X } from 'lucide-react';
import { isWebPushUiEnabled } from './flags';
import { useWebPush } from './useWebPush';

export const BANNER_DISMISSED_KEY = 'custom.webpush.bannerDismissed';

function dismissed(): boolean {
  try {
    return localStorage.getItem(BANNER_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Convite de um toque, uma vez, no topo do app (Layout). Só aparece quando dá para ativar
 * aqui e agora (HTTPS, suportado, permissão ainda não pedida). "Agora não" some para
 * sempre neste navegador; o cartão em Configurações → Notificações continua lá.
 *
 * Também recebe o pedido de navegação do service worker (clique numa notificação com o
 * app aberto mas sem controle do SW) e roteia pelo React Router.
 */
export function WebPushPromptBanner() {
  if (!isWebPushUiEnabled()) return null;
  return <WebPushPromptBannerInner />;
}

function WebPushPromptBannerInner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [hidden, setHidden] = useState(dismissed);
  const permissionDefault = typeof Notification !== 'undefined' && Notification.permission === 'default';
  const { status, busy, enable } = useWebPush(!hidden && permissionDefault);

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; url?: string } | null;
      if (data?.type === 'custom-webpush-navigate' && typeof data.url === 'string' && data.url.startsWith('/')) {
        navigate(data.url);
      }
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [navigate]);

  if (hidden || !permissionDefault || status !== 'off') return null;

  const dismiss = () => {
    try {
      localStorage.setItem(BANNER_DISMISSED_KEY, '1');
    } catch {
      /* sem localStorage: some só nesta sessão */
    }
    setHidden(true);
  };

  return (
    <div
      className="mx-3 mt-3 sm:mx-6 flex items-center gap-2 rounded-lg border border-bambu-green/40 bg-bambu-green/10 px-3 py-2"
      role="region"
      aria-label={t('customWebPush.title')}
      data-testid="custom-webpush-banner"
    >
      <BellRing className="w-4 h-4 shrink-0 text-bambu-green" />
      <p className="flex-1 min-w-0 text-sm text-white">{t('customWebPush.bannerText')}</p>
      <button
        type="button"
        onClick={async () => {
          const ok = await enable();
          if (ok || Notification.permission !== 'default') setHidden(true);
        }}
        disabled={busy}
        className="shrink-0 min-h-10 rounded-md bg-bambu-green px-3 text-sm font-medium text-white disabled:opacity-60"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : t('customWebPush.bannerEnable')}
      </button>
      <button
        type="button"
        onClick={dismiss}
        className="shrink-0 min-h-10 min-w-10 flex items-center justify-center rounded-md text-bambu-gray hover:text-white"
        aria-label={t('customWebPush.bannerDismiss')}
        title={t('customWebPush.bannerDismiss')}
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
