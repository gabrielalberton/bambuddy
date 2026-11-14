import type { CatalogSourceId } from './types';

/** Alvo de toque >= 44 px (celular/PWA é o uso principal). */
export const controlClass =
  'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-bambu-dark-tertiary px-3 py-2 text-sm text-white hover:border-bambu-green focus-visible:outline focus-visible:outline-2 focus-visible:outline-bambu-green focus-visible:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

export const sourceName: Record<CatalogSourceId, string> = {
  makerworld: 'MakerWorld',
  printables: 'Printables',
  thingiverse: 'Thingiverse',
};
