/**
 * Interruptores das personalizações do fork (ver custom/CUSTOMIZATIONS.md).
 *
 * SINGLE_PRINTER_MODE ("modo impressora única"):
 *  - 'auto': liga sozinho quando o usuário enxerga exatamente uma impressora;
 *  - 'on':   sempre ligado (usa a primeira impressora da lista);
 *  - 'off':  comportamento original do upstream.
 *
 * Nos testes (vitest, MODE === 'test') o modo efetivo é 'off', para que toda a
 * suíte do upstream continue passando sem alteração. Um teste nosso liga o modo
 * com setSinglePrinterModeOverride().
 *
 * Para depurar no navegador sem recompilar:
 *   localStorage.setItem('custom.singlePrinterMode', 'off')  // ou 'on' / 'auto'
 */
export type SinglePrinterMode = 'auto' | 'on' | 'off';

export const SINGLE_PRINTER_MODE: SinglePrinterMode = 'auto';

export const SINGLE_PRINTER_MODE_STORAGE_KEY = 'custom.singlePrinterMode';

let modeOverride: SinglePrinterMode | null = null;

/** Só para testes: força um modo (null volta ao padrão). */
export function setSinglePrinterModeOverride(mode: SinglePrinterMode | null): void {
  modeOverride = mode;
}

function isMode(value: unknown): value is SinglePrinterMode {
  return value === 'auto' || value === 'on' || value === 'off';
}

export function getSinglePrinterMode(): SinglePrinterMode {
  if (modeOverride) return modeOverride;
  if (import.meta.env.MODE === 'test') return 'off';
  try {
    const stored = localStorage.getItem(SINGLE_PRINTER_MODE_STORAGE_KEY);
    if (isMode(stored)) return stored;
  } catch {
    /* localStorage indisponível (modo privado etc.) */
  }
  return SINGLE_PRINTER_MODE;
}
