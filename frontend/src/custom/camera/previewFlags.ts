/**
 * Interruptor da prévia instantânea da câmera (custom/docs/camera-previa.md).
 * Padrão: ligada fora dos testes do vitest (a suíte do upstream não espera o <img> extra).
 * `localStorage['custom.cameraPreview'] = 'off' | 'on'` força; `setCameraPreviewOverride()` é para os testes nossos.
 */
let override: boolean | null = null;

export function setCameraPreviewOverride(value: boolean | null) {
  override = value;
}

export function cameraPreviewEnabled(): boolean {
  if (override !== null) return override;
  try {
    const stored = localStorage.getItem('custom.cameraPreview');
    if (stored === 'off') return false;
    if (stored === 'on') return true;
  } catch {
    // localStorage indisponível: segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}
