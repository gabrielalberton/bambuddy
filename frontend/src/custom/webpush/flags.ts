/**
 * Interruptor do Web Push do fork (ver custom/docs/notificacoes-pwa.md).
 *
 * - Padrão: ligado. Se o backend não tiver as rotas (BAMBUDDY_CUSTOM_WEBPUSH=0), a UI
 *   detecta o 404 e some sozinha.
 * - Desligar só a UI neste navegador: localStorage.setItem('custom.webPush', 'off').
 * - Nos testes (vitest, MODE === 'test') fica desligado, para a suíte do upstream não
 *   ver o cartão/banner nem fazer requisições a mais; testes nossos ligam com
 *   setWebPushOverride(true).
 */
export const WEB_PUSH_STORAGE_KEY = 'custom.webPush';

let override: boolean | null = null;

export function setWebPushOverride(value: boolean | null): void {
  override = value;
}

export function isWebPushUiEnabled(): boolean {
  if (override !== null) return override;
  if (import.meta.env.MODE === 'test') return false;
  try {
    if (localStorage.getItem(WEB_PUSH_STORAGE_KEY) === 'off') return false;
  } catch {
    /* localStorage indisponível */
  }
  return true;
}

/** Entra na lista de tipos do AddNotificationModal (sem campos de configuração). Fica de
 *  fora nos testes do upstream, que conferem a lista exata de provedores. */
export function webPushProviderValues(): Array<'webpush'> {
  return isWebPushUiEnabled() ? ['webpush'] : [];
}
