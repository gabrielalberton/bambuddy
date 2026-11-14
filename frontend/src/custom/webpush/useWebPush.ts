import { useCallback, useEffect, useState } from 'react';
import { webPushApi, WebPushApiError } from './api';

/**
 * Estado do Web Push neste aparelho/navegador.
 *
 * - unsupported: navegador sem Service Worker / PushManager / Notification;
 * - insecure:    página fora de HTTPS (ex.: http://100.81.104.50:PORTA) — push exige contexto seguro;
 * - ios-install: iPhone/iPad fora do app instalado (no iOS só funciona no PWA da tela inicial);
 * - backend-off: o servidor não tem as rotas (BAMBUDDY_CUSTOM_WEBPUSH=0 ou imagem do upstream);
 * - denied:      permissão negada (só se desfaz nas configurações do site/app);
 * - off:         pode ativar (permissão ainda não pedida ou já concedida, sem inscrição);
 * - on:          inscrito e registrado no servidor.
 */
export type WebPushStatus =
  | 'checking'
  | 'unsupported'
  | 'insecure'
  | 'ios-install'
  | 'backend-off'
  | 'denied'
  | 'off'
  | 'on';

export interface SupportEnv {
  isSecureContext: boolean;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  userAgent: string;
  maxTouchPoints: number;
  standalone: boolean;
}

export function isIos(env: Pick<SupportEnv, 'userAgent' | 'maxTouchPoints'>): boolean {
  // iPadOS se apresenta como Mac; o toque denuncia.
  return /iPad|iPhone|iPod/.test(env.userAgent) || (/Macintosh/.test(env.userAgent) && env.maxTouchPoints > 1);
}

/** Diagnóstico sem efeito colateral (testável). null = pode seguir. */
export function detectSupport(env: SupportEnv): WebPushStatus | null {
  if (!env.isSecureContext) return 'insecure';
  if (isIos(env) && !env.standalone) return 'ios-install';
  if (!env.hasServiceWorker || !env.hasPushManager || !env.hasNotification) return 'unsupported';
  return null;
}

export function currentEnv(): SupportEnv {
  const nav = typeof navigator !== 'undefined' ? navigator : ({} as Navigator);
  const standalone =
    (typeof window !== 'undefined' && window.matchMedia?.('(display-mode: standalone)').matches) ||
    (nav as Navigator & { standalone?: boolean }).standalone === true;
  return {
    isSecureContext: typeof window !== 'undefined' && window.isSecureContext === true,
    hasServiceWorker: 'serviceWorker' in nav,
    hasPushManager: typeof window !== 'undefined' && 'PushManager' in window,
    hasNotification: typeof window !== 'undefined' && 'Notification' in window,
    userAgent: nav.userAgent || '',
    maxTouchPoints: nav.maxTouchPoints || 0,
    standalone: !!standalone,
  };
}

export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function sameKey(a: ArrayBuffer | null | undefined, b: Uint8Array): boolean {
  if (!a) return false;
  const x = new Uint8Array(a);
  return x.length === b.length && x.every((v, i) => v === b[i]);
}

async function readyRegistration(timeoutMs = 10000): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration();
  if (existing?.active) return existing;
  return await Promise.race([
    navigator.serviceWorker.ready,
    new Promise<never>((_, reject) => setTimeout(() => reject(new Error('sw-timeout')), timeoutMs)),
  ]);
}

// Uma sincronização por carga de página, compartilhada pelo cartão e pelo banner.
let syncPromise: Promise<{ status: WebPushStatus; endpoint: string | null }> | null = null;

/** Só para testes. */
export function resetWebPushSync(): void {
  syncPromise = null;
}

async function subscribeWith(reg: ServiceWorkerRegistration, key: Uint8Array<ArrayBuffer>): Promise<PushSubscription> {
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await webPushApi.subscribe(sub.toJSON());
  return sub;
}

async function sync(): Promise<{ status: WebPushStatus; endpoint: string | null }> {
  const unsupported = detectSupport(currentEnv());
  if (unsupported) return { status: unsupported, endpoint: null };
  let key: Uint8Array<ArrayBuffer>;
  try {
    key = urlBase64ToUint8Array((await webPushApi.publicKey()).public_key);
  } catch (e) {
    if (e instanceof WebPushApiError && e.status === 404) return { status: 'backend-off', endpoint: null };
    throw e;
  }
  if (Notification.permission === 'denied') return { status: 'denied', endpoint: null };
  const reg = await navigator.serviceWorker.getRegistration();
  const existing = reg ? await reg.pushManager.getSubscription() : null;
  if (!existing || Notification.permission !== 'granted') return { status: 'off', endpoint: null };
  if (!sameKey(existing.options.applicationServerKey, key)) {
    // Chave VAPID do servidor mudou (vapid.json apagado/restaurado): refaz a inscrição.
    await existing.unsubscribe().catch(() => {});
    const sub = await subscribeWith(reg!, key);
    return { status: 'on', endpoint: sub.endpoint };
  }
  // Re-registra a cada carga: renova dono/chaves e recria se o servidor a tinha apagado (410).
  await webPushApi.subscribe(existing.toJSON());
  return { status: 'on', endpoint: existing.endpoint };
}

export function useWebPush(enabled = true) {
  const [status, setStatus] = useState<WebPushStatus>('checking');
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    if (!syncPromise) syncPromise = sync();
    syncPromise.then(
      (r) => {
        if (!alive) return;
        setStatus(r.status);
        setEndpoint(r.endpoint);
      },
      (e: unknown) => {
        syncPromise = null;
        if (!alive) return;
        setStatus('off');
        setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      alive = false;
    };
  }, [enabled]);

  /** Precisa ser chamado direto de um toque/clique (pedido de permissão). */
  const enable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setStatus(permission === 'denied' ? 'denied' : 'off');
        return false;
      }
      const key = urlBase64ToUint8Array((await webPushApi.publicKey()).public_key);
      const reg = await readyRegistration();
      const old = await reg.pushManager.getSubscription();
      if (old && !sameKey(old.options.applicationServerKey, key)) await old.unsubscribe().catch(() => {});
      const sub = await subscribeWith(reg, key);
      setEndpoint(sub.endpoint);
      setStatus('on');
      syncPromise = Promise.resolve({ status: 'on', endpoint: sub.endpoint });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      if (sub) {
        await webPushApi.unsubscribe(sub.endpoint).catch(() => {});
        await sub.unsubscribe();
      }
      setEndpoint(null);
      setStatus('off');
      syncPromise = Promise.resolve({ status: 'off', endpoint: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const sendTest = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      return await webPushApi.test(endpoint ?? undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, [endpoint]);

  return { status, endpoint, error, busy, enable, disable, sendTest };
}
