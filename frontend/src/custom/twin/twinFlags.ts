/**
 * Interruptor do gêmeo digital (chave "Câmera | 3D" nos visualizadores de câmera da A1).
 *
 *  - TWIN_VIEW = true: a chave aparece para impressoras A1 (o backend também precisa estar ligado:
 *    `BAMBUDDY_CUSTOM_TWIN` != '0').
 *  - Sem recompilar, no navegador: `localStorage.setItem('custom.twin', 'off')` (ou 'on') e recarregar.
 *  - Nos testes (vitest) fica desligado, para a suíte do upstream rodar sem alteração; testes nossos ligam com
 *    `setTwinOverride(true)`.
 */
export const TWIN_VIEW = true;
export const TWIN_FLAG_STORAGE_KEY = 'custom.twin';

let override: boolean | null = null;

/** Só para testes. */
export function setTwinOverride(value: boolean | null): void {
  override = value;
}

export function isTwinEnabled(): boolean {
  if (override !== null) return override;
  if (import.meta.env.MODE === 'test') return false;
  try {
    const v = localStorage.getItem(TWIN_FLAG_STORAGE_KEY);
    if (v === 'off') return false;
    if (v === 'on') return true;
  } catch {
    /* sem localStorage: vale o padrão */
  }
  return TWIN_VIEW;
}

/** Modelos com geometria no twin (a cena é a da A1; a A1 Mini é outra máquina). */
export function isTwinModel(model: string | null | undefined): boolean {
  const m = (model || '').trim().toUpperCase();
  return m === 'A1' || m === 'N2S' || m === 'A11';
}
