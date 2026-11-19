import type {
  CatalogFilterDef,
  CatalogFilterSchema,
  CatalogFilterValue,
  CatalogFilters,
  CatalogLabel,
  CatalogSourceId,
} from './types';

/** Filtro avançado por fonte, lembrado neste navegador (o backend valida de novo contra o esquema). */
export const FILTERS_KEY_PREFIX = 'custom.models.filters.';
/** MakerWorld: ``model_tag=cb`` (chave CyberBrick fixa na barra). */
export const CYBERBRICK_FILTER = 'model_tag';
export const CYBERBRICK_VALUE = 'cb';

export function readFilters(source: CatalogSourceId): CatalogFilters {
  try {
    const raw = localStorage.getItem(FILTERS_KEY_PREFIX + source);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as CatalogFilters) : {};
  } catch {
    return {};
  }
}

export function writeFilters(source: CatalogSourceId, filters: CatalogFilters): void {
  try {
    if (Object.keys(filters).length) localStorage.setItem(FILTERS_KEY_PREFIX + source, JSON.stringify(filters));
    else localStorage.removeItem(FILTERS_KEY_PREFIX + source);
  } catch {
    /* só não lembra */
  }
}

export function pickLabel(label: CatalogLabel | undefined, language: string | undefined): string {
  if (!label) return '';
  return language?.toLowerCase().startsWith('pt') ? label.pt : label.en;
}

function isEmpty(value: CatalogFilterValue | undefined | null): boolean {
  if (value == null || value === false || value === '') return true;
  if (Array.isArray(value)) return value.every((v) => v == null || v === '');
  return false;
}

/** Remove vazios (o que sobra é o que conta no botão e vira chip). */
export function compact(filters: CatalogFilters): CatalogFilters {
  const out: CatalogFilters = {};
  for (const [id, value] of Object.entries(filters)) if (!isEmpty(value)) out[id] = value;
  return out;
}

export function countActive(filters: CatalogFilters): number {
  return Object.keys(compact(filters)).length;
}

/** Descarta o que o esquema atual não conhece (a fonte mudou as opções desde que foi salvo). */
export function sanitize(filters: CatalogFilters, schema: CatalogFilterSchema): CatalogFilters {
  const defs = new Map(schema.groups.flatMap((g) => g.filters.map((f) => [f.id, f] as const)));
  const out: CatalogFilters = {};
  for (const [id, value] of Object.entries(compact(filters))) {
    const def = defs.get(id);
    if (!def) continue;
    const allowed = new Set(def.options.map((o) => o.value));
    if (def.type === 'bool') {
      if (value === true) out[id] = true;
    } else if (def.type === 'enum' || def.type === 'days') {
      if (typeof value === 'string' && allowed.has(value)) out[id] = value;
    } else if (def.type === 'multi') {
      const list = Array.isArray(value) ? (value as unknown[]).filter((v): v is string => typeof v === 'string' && allowed.has(v)) : [];
      if (list.length) out[id] = list;
    } else if (def.type === 'range' && Array.isArray(value) && value.length === 2) {
      const [lo, hi] = (value as unknown[]).map((v) => (typeof v === 'string' && allowed.has(v) ? v : null)) as [string | null, string | null];
      const order = def.options.map((o) => o.value);
      if ((lo || hi) && !(lo && hi && order.indexOf(lo) >= order.indexOf(hi)) && !(def.requires_min && !lo)) out[id] = [lo, hi];
    }
  }
  return out;
}

/** Texto do chip de um filtro ativo ("Tipo de bico: Alto fluxo, Padrão"). */
export function describe(def: CatalogFilterDef | undefined, id: string, value: CatalogFilterValue, language: string | undefined): string {
  if (!def) return id;
  const name = pickLabel(def.label, language);
  const opt = (v: string | null) => (v == null ? null : pickLabel(def.options.find((o) => o.value === v)?.label, language) || v);
  if (def.type === 'bool') return name;
  if (def.type === 'range' && Array.isArray(value)) {
    const [lo, hi] = value as [string | null, string | null];
    const pt = language?.toLowerCase().startsWith('pt');
    if (!lo) return `${name}: ${pt ? 'até' : 'up to'} ${opt(hi)}`;
    if (!hi) return `${name}: ${pt ? 'a partir de' : 'from'} ${opt(lo)}`;
    return `${name}: ${opt(lo)} – ${opt(hi)}`;
  }
  if (Array.isArray(value)) return `${name}: ${(value as string[]).map((v) => opt(v)).join(', ')}`;
  return `${name}: ${opt(String(value))}`;
}
