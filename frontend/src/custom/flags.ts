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

/**
 * MODEL_CATALOG ("catálogo de modelos" na página Fontes de modelos):
 *  - 'on':  aba "Catálogo" (MakerWorld/Printables/... com filtro da impressora) ligada;
 *  - 'off': página do upstream intacta.
 * Nos testes o efetivo é 'off' (suíte do upstream sem alteração); testes nossos
 * usam setModelCatalogOverride(). No navegador:
 *   localStorage.setItem('custom.modelCatalog', 'off')
 * O backend tem o interruptor próprio BAMBUDDY_CUSTOM_MODELS_CATALOG.
 */
export type ModelCatalogMode = 'on' | 'off';

export const MODEL_CATALOG: ModelCatalogMode = 'on';

export const MODEL_CATALOG_STORAGE_KEY = 'custom.modelCatalog';

let catalogOverride: ModelCatalogMode | null = null;

/** Só para testes. */
export function setModelCatalogOverride(mode: ModelCatalogMode | null): void {
  catalogOverride = mode;
}

export function isModelCatalogEnabled(): boolean {
  if (catalogOverride) return catalogOverride === 'on';
  if (import.meta.env.MODE === 'test') return false;
  try {
    const stored = localStorage.getItem(MODEL_CATALOG_STORAGE_KEY);
    if (stored === 'on' || stored === 'off') return stored === 'on';
  } catch {
    /* localStorage indisponível */
  }
  return MODEL_CATALOG === 'on';
}

/**
 * FILAMENT_LIST ("filamentos em lista" no card da impressora, só no modo impressora única):
 *  - 'on':  seção FILAMENTS sem cabeçalhos, um slot por linha (bolinha, material, barra);
 *  - 'off': grade de tiles do upstream.
 * Nos testes o efetivo é 'off'; testes nossos usam setFilamentListOverride(). No navegador:
 *   localStorage.setItem('custom.filamentList', 'off')
 */
export type FilamentListMode = 'on' | 'off';

export const FILAMENT_LIST: FilamentListMode = 'on';

export const FILAMENT_LIST_STORAGE_KEY = 'custom.filamentList';

let filamentListOverride: FilamentListMode | null = null;

/** Só para testes. */
export function setFilamentListOverride(mode: FilamentListMode | null): void {
  filamentListOverride = mode;
}

export function isFilamentListEnabled(): boolean {
  if (filamentListOverride) return filamentListOverride === 'on';
  if (import.meta.env.MODE === 'test') return false;
  try {
    const stored = localStorage.getItem(FILAMENT_LIST_STORAGE_KEY);
    if (stored === 'on' || stored === 'off') return stored === 'on';
  } catch {
    /* localStorage indisponível */
  }
  return FILAMENT_LIST === 'on';
}

/**
 * TEMP_BARS ("barras de temperatura" no card da impressora, bico e mesa):
 *  - 'on':  barrinha no estilo da de filamento embaixo da temperatura;
 *  - 'off': cartões de temperatura do upstream intactos.
 * Nos testes o efetivo é 'off'; testes nossos usam setTempBarsOverride(). No navegador:
 *   localStorage.setItem('custom.tempBars', 'off')
 */
export type TempBarsMode = 'on' | 'off';

export const TEMP_BARS: TempBarsMode = 'on';

export const TEMP_BARS_STORAGE_KEY = 'custom.tempBars';

let tempBarsOverride: TempBarsMode | null = null;

/** Só para testes. */
export function setTempBarsOverride(mode: TempBarsMode | null): void {
  tempBarsOverride = mode;
}

export function isTempBarsEnabled(): boolean {
  if (tempBarsOverride) return tempBarsOverride === 'on';
  if (import.meta.env.MODE === 'test') return false;
  try {
    const stored = localStorage.getItem(TEMP_BARS_STORAGE_KEY);
    if (stored === 'on' || stored === 'off') return stored === 'on';
  } catch {
    /* localStorage indisponível */
  }
  return TEMP_BARS === 'on';
}

/**
 * CATALOG_FILTERS ("filtro avançado" do catálogo de modelos: botão Filtros com o modal por fonte, chips dos filtros
 * ativos, chave CyberBrick do MakerWorld e selo CyberBrick no card):
 *  - 'on':  ligado;
 *  - 'off': catálogo como antes (só busca, ordem, categoria e filtro da impressora).
 * Nos testes o efetivo é 'off'; testes nossos usam setCatalogFiltersOverride(). No navegador:
 *   localStorage.setItem('custom.catalogFilters', 'off')
 */
export type CatalogFiltersMode = 'on' | 'off';

export const CATALOG_FILTERS: CatalogFiltersMode = 'on';

export const CATALOG_FILTERS_STORAGE_KEY = 'custom.catalogFilters';

let catalogFiltersOverride: CatalogFiltersMode | null = null;

/** Só para testes. */
export function setCatalogFiltersOverride(mode: CatalogFiltersMode | null): void {
  catalogFiltersOverride = mode;
}

export function isCatalogFiltersEnabled(): boolean {
  if (catalogFiltersOverride) return catalogFiltersOverride === 'on';
  if (import.meta.env.MODE === 'test') return false;
  try {
    const stored = localStorage.getItem(CATALOG_FILTERS_STORAGE_KEY);
    if (stored === 'on' || stored === 'off') return stored === 'on';
  } catch {
    /* localStorage indisponível */
  }
  return CATALOG_FILTERS === 'on';
}

/** No navegador, custom.editUserOverlay = 'off' restaura o layout anterior. */
export function isEditUserOverlayEnabled(): boolean {
  try {
    return localStorage.getItem('custom.editUserOverlay') !== 'off';
  } catch {
    return true;
  }
}
