import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { http, HttpResponse } from 'msw';
import { render } from '../../__tests__/utils';
import { server } from '../../__tests__/mocks/server';
import i18n from '../i18n';
import { setWebPushOverride } from '../webpush/flags';
import { detectSupport, resetWebPushSync, urlBase64ToUint8Array, type SupportEnv } from '../webpush/useWebPush';
import { WebPushDeviceCard } from '../webpush/WebPushDeviceCard';
import { WebPushPromptBanner, BANNER_DISMISSED_KEY } from '../webpush/WebPushPromptBanner';
import { recommendedWebPushProvider } from '../webpush/recommended';
import { installMemoryStorage } from './fixtures';

// Chave pública P-256 do RFC 8291 (65 bytes) — só precisa ter o formato certo.
const PUBLIC_KEY = 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4';
const ENDPOINT = 'https://fcm.googleapis.com/fcm/send/fake-device';

const baseEnv: SupportEnv = {
  isSecureContext: true,
  hasServiceWorker: true,
  hasPushManager: true,
  hasNotification: true,
  userAgent: 'Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile',
  maxTouchPoints: 5,
  standalone: true,
};

describe('detectSupport', () => {
  it('Android Chrome em HTTPS pode seguir', () => {
    expect(detectSupport(baseEnv)).toBeNull();
  });
  it('http:// por IP não é contexto seguro', () => {
    expect(detectSupport({ ...baseEnv, isSecureContext: false })).toBe('insecure');
  });
  it('iPhone fora do PWA instalado precisa instalar', () => {
    const ios = { ...baseEnv, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', standalone: false };
    expect(detectSupport(ios)).toBe('ios-install');
    expect(detectSupport({ ...ios, standalone: true })).toBeNull();
  });
  it('iPad se passando por Mac também conta como iOS', () => {
    expect(detectSupport({ ...baseEnv, userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)', standalone: false })).toBe('ios-install');
  });
  it('sem PushManager não há suporte', () => {
    expect(detectSupport({ ...baseEnv, hasPushManager: false })).toBe('unsupported');
  });
});

it('urlBase64ToUint8Array decodifica a chave VAPID (65 bytes, 0x04)', () => {
  const bytes = urlBase64ToUint8Array(PUBLIC_KEY);
  expect(bytes.length).toBe(65);
  expect(bytes[0]).toBe(4);
});

it('preset recomendado liga só os eventos combinados', () => {
  const p = recommendedWebPushProvider('Celular');
  expect(p.provider_type).toBe('webpush');
  expect(p.config).toEqual({});
  const on = Object.entries(p).filter(([k, v]) => k.startsWith('on_') && v === true).map(([k]) => k).sort();
  expect(on).toEqual(
    [
      'on_filament_low',
      'on_plate_clear_required',
      'on_print_complete',
      'on_print_failed',
      'on_print_stopped',
      'on_printer_error',
      'on_queue_job_failed',
      'on_queue_job_waiting',
    ].sort(),
  );
});

describe('i18n do fork', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });
  it('mescla em inglês sem apagar textos do upstream', () => {
    expect(i18n.t('notifications.providerTypes.webpush')).toBe('Web Push (PWA)');
    expect(i18n.t('customWebPush.title')).toBe('Notifications on this device');
    expect(i18n.t('notifications.providerTypes.email')).toBe('Email');
  });
  it('mescla em pt-BR depois que o arquivo do upstream carrega', async () => {
    await i18n.changeLanguage('pt-BR');
    expect(i18n.t('customWebPush.title')).toBe('Notificações neste aparelho');
    // o arquivo pt-BR do upstream continua carregado (não foi "pulado")
    expect(i18n.t('notifications.providerTypes.email')).not.toBe('');
    expect(i18n.getResource('pt-BR', 'translation', 'settings.providers')).toBeTruthy();
  });
});

// --- service worker add-on ---------------------------------------------------------

type Listener = (event: unknown) => void;

function loadSwPush(clients: Array<{ url: string; focus: () => Promise<unknown>; navigate?: (u: string) => Promise<unknown>; postMessage?: (m: unknown) => void }>) {
  const code = readFileSync(resolve(__dirname, '../../../public/custom/sw-push.js'), 'utf8');
  const listeners: Record<string, Listener> = {};
  const showNotification = vi.fn(() => Promise.resolve());
  const openWindow = vi.fn(() => Promise.resolve(null));
  const fakeSelf = {
    location: { origin: 'https://bambu.example' },
    addEventListener: (name: string, fn: Listener) => {
      listeners[name] = fn;
    },
    registration: { showNotification },
    clients: { matchAll: vi.fn(() => Promise.resolve(clients)), openWindow },
  };
  new Function('self', code)(fakeSelf);
  return { listeners, showNotification, openWindow };
}

async function dispatch(listener: Listener, event: Record<string, unknown>) {
  let pending: Promise<unknown> = Promise.resolve();
  listener({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) });
  await pending;
}

describe('sw-push.js', () => {
  it('push com payload JSON mostra a notificação com tag, ícone e link', async () => {
    const { listeners, showNotification } = loadSwPush([]);
    const payload = { title: 'Impressão concluída', body: 'benchy', url: '/archives/3', tag: 'bambuddy-print_complete-1', renotify: true, image: '/api/v1/notifications/photos/x.jpg' };
    await dispatch(listeners.push, { data: { json: () => payload, text: () => JSON.stringify(payload) } });
    expect(showNotification).toHaveBeenCalledTimes(1);
    const [title, options] = showNotification.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(title).toBe('Impressão concluída');
    expect(options).toMatchObject({ body: 'benchy', tag: 'bambuddy-print_complete-1', renotify: true, icon: '/img/android-chrome-192x192.png', badge: '/custom/webpush-badge.png', image: '/api/v1/notifications/photos/x.jpg' });
    expect((options.data as { url: string }).url).toBe('/archives/3');
  });

  it('push sem payload ainda mostra uma notificação genérica', async () => {
    const { listeners, showNotification } = loadSwPush([]);
    await dispatch(listeners.push, { data: null });
    const [title, options] = showNotification.mock.calls[0] as unknown as [string, { body: string }];
    expect(title).toBe('Bambuddy');
    expect(options.body).toBeTruthy();
  });

  it('URL de outra origem vira "/"', async () => {
    const { listeners, showNotification } = loadSwPush([]);
    await dispatch(listeners.push, { data: { json: () => ({ title: 'x', url: 'https://evil.example/phish' }) } });
    const options = (showNotification.mock.calls[0] as unknown as [string, { data: { url: string } }])[1];
    expect(options.data.url).toBe('/');
  });

  it('clique foca o PWA aberto e navega até a página', async () => {
    const navigate = vi.fn(() => Promise.resolve(null));
    const client = { url: 'https://bambu.example/', focus: vi.fn(() => Promise.resolve(client)), navigate };
    const { listeners, openWindow } = loadSwPush([client]);
    const close = vi.fn();
    await dispatch(listeners.notificationclick, { notification: { close, data: { url: '/queue' } } });
    expect(close).toHaveBeenCalled();
    expect(client.focus).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('https://bambu.example/queue');
    expect(openWindow).not.toHaveBeenCalled();
  });

  it('clique sem janela aberta abre o app na página', async () => {
    const { listeners, openWindow } = loadSwPush([]);
    await dispatch(listeners.notificationclick, { notification: { close: vi.fn(), data: { url: '/archives/9' } } });
    expect(openWindow).toHaveBeenCalledWith('https://bambu.example/archives/9');
  });
});

// --- UI ---------------------------------------------------------------------------

interface FakePush {
  subscription: { endpoint: string; options: { applicationServerKey: ArrayBuffer }; toJSON: () => unknown; unsubscribe: () => Promise<boolean> } | null;
}

function installBrowserPush(permission: NotificationPermission, push: FakePush) {
  const requestPermission = vi.fn(async () => {
    (globalThis.Notification as unknown as { permission: string }).permission = 'granted';
    return 'granted' as NotificationPermission;
  });
  vi.stubGlobal('Notification', { permission, requestPermission });
  vi.stubGlobal('PushManager', function PushManager() {});
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true });
  const pushManager = {
    getSubscription: vi.fn(async () => push.subscription),
    subscribe: vi.fn(async ({ applicationServerKey }: { applicationServerKey: Uint8Array }) => {
      push.subscription = {
        endpoint: ENDPOINT,
        options: { applicationServerKey: applicationServerKey.slice().buffer },
        toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: PUBLIC_KEY, auth: 'AAAAAAAAAAAAAAAAAAAAAA' } }),
        unsubscribe: vi.fn(async () => true),
      };
      return push.subscription;
    }),
  };
  const registration = { active: {}, pushManager };
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => registration),
      ready: Promise.resolve(registration),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
  return { requestPermission, pushManager };
}

describe('cartão "Notificações neste aparelho"', () => {
  let calls: string[];
  beforeEach(() => {
    installMemoryStorage();
    resetWebPushSync();
    setWebPushOverride(true);
    calls = [];
    server.use(
      http.get('/api/v1/custom/webpush/public-key', () => HttpResponse.json({ public_key: PUBLIC_KEY })),
      http.post('/api/v1/custom/webpush/subscribe', async ({ request }) => {
        calls.push(`subscribe ${(await request.json() as { endpoint: string }).endpoint}`);
        return HttpResponse.json({ id: 1, created: true });
      }),
      http.delete('/api/v1/custom/webpush/subscribe', () => {
        calls.push('unsubscribe');
        return HttpResponse.json({ deleted: 1 });
      }),
      http.get('/api/v1/custom/webpush/devices', () =>
        HttpResponse.json([{ id: 1, service: 'fcm.googleapis.com', user_agent: 'x', created_at: null, last_success_at: null, last_error: null, this_device: true }]),
      ),
      http.post('/api/v1/custom/webpush/test', () => {
        calls.push('test');
        return HttpResponse.json({ sent: 1, failed: 0, removed: 0, errors: [] });
      }),
      http.get('*/api/v1/notifications/', () => HttpResponse.json([])),
      http.post('*/api/v1/notifications/', async ({ request }) => {
        calls.push(`create ${(await request.json() as { provider_type: string }).provider_type}`);
        return HttpResponse.json({ id: 5 });
      }),
    );
  });
  afterEach(() => {
    setWebPushOverride(null);
    vi.unstubAllGlobals();
  });

  it('ativa com um toque, manda teste, oferece criar o canal e desativa', async () => {
    const { requestPermission, pushManager } = installBrowserPush('default', { subscription: null });
    render(<WebPushDeviceCard />);
    const enable = await screen.findByRole('button', { name: /Enable on this device/ });
    fireEvent.click(enable);
    await waitFor(() => expect(screen.getByTestId('custom-webpush-status').textContent).toMatch(/On: this device/));
    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(calls).toContain(`subscribe ${ENDPOINT}`);

    fireEvent.click(screen.getByRole('button', { name: /Send test/ }));
    expect(await screen.findByText('Test sent to 1 device(s).')).not.toBeNull();

    fireEvent.click(await screen.findByRole('button', { name: /Create Web Push channel/ }));
    await waitFor(() => expect(calls).toContain('create webpush'));

    fireEvent.click(screen.getByRole('button', { name: /Disable/ }));
    await waitFor(() => expect(screen.getByTestId('custom-webpush-status').textContent).toMatch(/Off on this device/));
    expect(calls).toContain('unsubscribe');
  });

  it('já inscrito: re-registra no servidor ao abrir', async () => {
    const key = urlBase64ToUint8Array(PUBLIC_KEY);
    installBrowserPush('granted', {
      subscription: {
        endpoint: ENDPOINT,
        options: { applicationServerKey: key.slice().buffer },
        toJSON: () => ({ endpoint: ENDPOINT, keys: {} }),
        unsubscribe: async () => true,
      },
    });
    render(<WebPushDeviceCard />);
    await waitFor(() => expect(screen.getByTestId('custom-webpush-status').textContent).toMatch(/On: this device/));
    expect(calls).toEqual([`subscribe ${ENDPOINT}`]);
  });

  it('permissão negada mostra como liberar e não oferece botão', async () => {
    installBrowserPush('denied', { subscription: null });
    render(<WebPushDeviceCard />);
    await waitFor(() => expect(screen.getByTestId('custom-webpush-status').textContent).toMatch(/blocked/));
    expect(screen.queryByRole('button', { name: /Enable/ })).toBeNull();
  });

  it('backend sem Web Push: cartão some', async () => {
    installBrowserPush('default', { subscription: null });
    server.use(http.get('/api/v1/custom/webpush/public-key', () => new HttpResponse(null, { status: 404 })));
    const { container } = render(<WebPushDeviceCard />);
    await waitFor(() => expect(container.querySelector('[data-testid="custom-webpush-card"]')).toBeNull());
  });

  it('desligado por padrão nos testes do upstream', () => {
    setWebPushOverride(null);
    render(<WebPushDeviceCard />);
    expect(screen.queryByTestId('custom-webpush-card')).toBeNull();
  });
});

describe('banner de convite', () => {
  beforeEach(() => {
    installMemoryStorage();
    resetWebPushSync();
    setWebPushOverride(true);
    server.use(http.get('/api/v1/custom/webpush/public-key', () => HttpResponse.json({ public_key: PUBLIC_KEY })));
  });
  afterEach(() => {
    setWebPushOverride(null);
    vi.unstubAllGlobals();
  });

  it('aparece uma vez e "Agora não" lembra', async () => {
    installBrowserPush('default', { subscription: null });
    const first = render(<WebPushPromptBanner />);
    expect(await screen.findByTestId('custom-webpush-banner')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByTestId('custom-webpush-banner')).toBeNull();
    expect(localStorage.getItem(BANNER_DISMISSED_KEY)).toBe('1');
    first.unmount();
    render(<WebPushPromptBanner />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('custom-webpush-banner')).toBeNull();
  });

  it('não aparece se a permissão já foi decidida', async () => {
    installBrowserPush('granted', { subscription: null });
    render(<WebPushPromptBanner />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('custom-webpush-banner')).toBeNull();
  });
});

it('AddNotificationModal lista "Web Push (PWA)" sem campos de configuração', async () => {
  // PROVIDER_VALUES é calculado no import do módulo: simula build de produção e importa de novo.
  vi.stubEnv('MODE', 'production');
  vi.resetModules();
  const { AddNotificationModal } = await import('../../components/AddNotificationModal');
  await import('../i18n');
  render(<AddNotificationModal onClose={() => {}} />);
  const option = (await screen.findByRole('option', { name: 'Web Push (PWA)' })) as HTMLOptionElement;
  expect(option.value).toBe('webpush');
  const select = option.closest('select') as HTMLSelectElement;
  fireEvent.change(select, { target: { value: 'webpush' } });
  await waitFor(() => expect(screen.getByText(/Native notifications on phones/)).not.toBeNull());
  expect(document.querySelector('[id^="notification-config-"]')).toBeNull();
  vi.unstubAllEnvs();
});
