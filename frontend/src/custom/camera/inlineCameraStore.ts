import { useSyncExternalStore } from 'react';

/**
 * Câmeras que estão embutidas no card da impressora (InlineCamera). Enquanto uma está montada, a janela flutuante
 * do upstream (EmbeddedCameraContext) não abre outra para a mesma impressora: um stream só.
 */
const ids = new Set<number>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  listeners.forEach((l) => l());
}

export function registerInlineCamera(id: number): () => void {
  ids.add(id);
  emit();
  return () => {
    ids.delete(id);
    emit();
  };
}

export function isInlineCamera(id: number): boolean {
  return ids.has(id);
}

/** Re-renderiza quem chama quando a lista muda (o valor em si é só um contador). */
export function useInlineCameraVersion(): number {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => version,
  );
}

export function inlineCameraEnabled(): boolean {
  try {
    const v = localStorage.getItem('custom.inlineCamera');
    if (v === 'off') return false;
    if (v === 'on') return true;
  } catch {
    // sem localStorage: segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}
