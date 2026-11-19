import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SlidersHorizontal, ToyBrick, X } from 'lucide-react';
import { useCatalogT } from './i18n';
import { controlClass } from './constants';
import { Switch } from './shared';
import { CYBERBRICK_FILTER, CYBERBRICK_VALUE, compact, countActive, describe, pickLabel } from './filters';
import type { CatalogFilterDef, CatalogFilterSchema, CatalogFilterValue, CatalogFilters } from './types';

const chipClass = (on: boolean) =>
  `inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-bambu-green ${
    on ? 'border-bambu-green bg-bambu-green/15 text-bambu-green' : 'border-bambu-dark-tertiary text-white'
  }`;

/** Botão "Filtros" da barra, com o contador de filtros ativos. */
export function FiltersButton({ count, onClick }: { count: number; onClick: () => void }) {
  const t = useCatalogT();
  return (
    <button
      type="button"
      className={`${controlClass} ${count ? '!border-bambu-green text-bambu-green' : ''}`}
      onClick={onClick}
      aria-label={count ? `${t('filters')} · ${t('filtersActive', { count })}` : t('filters')}
      aria-haspopup="dialog"
    >
      <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
      {t('filters')}
      {count > 0 && (
        <span className="min-w-5 rounded-full bg-bambu-green px-1.5 text-xs font-semibold text-black" aria-hidden="true">
          {count}
        </span>
      )}
    </button>
  );
}

/** Chave CyberBrick fixa na barra (MakerWorld ``model_tag=cb``). */
export function CyberBrickToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const t = useCatalogT();
  return (
    <button type="button" className={chipClass(on)} aria-pressed={on} title={t('cyberbrickHint')} onClick={() => onChange(!on)}>
      <ToyBrick className="h-4 w-4" aria-hidden="true" />
      {t('cyberbrick')}
    </button>
  );
}

/** Filtros ativos acima da grade, cada um removível (o CyberBrick tem a chave própria na barra). */
export function ActiveFilterChips({ filters, schema, onChange }: {
  filters: CatalogFilters;
  schema: CatalogFilterSchema | undefined;
  onChange: (next: CatalogFilters) => void;
}) {
  const t = useCatalogT();
  const { i18n } = useTranslation();
  const defs = new Map(schema?.groups.flatMap((g) => g.filters.map((f) => [f.id, f] as const)) ?? []);
  const entries = Object.entries(compact(filters)).filter(
    ([id, v]) => !(schema?.source === 'makerworld' && id === CYBERBRICK_FILTER && v === CYBERBRICK_VALUE),
  );
  if (!entries.length) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label={t('filtersActive', { count: entries.length })}>
      {entries.map(([id, value]) => {
        const text = describe(defs.get(id), id, value, i18n.language);
        return (
          <li key={id}>
            <button
              type="button"
              className="inline-flex min-h-9 max-w-full items-center gap-1 rounded-full border border-bambu-green/60 bg-bambu-green/10 py-1 pl-3 pr-2 text-xs text-bambu-green"
              onClick={() => {
                const next = { ...filters };
                delete next[id];
                onChange(next);
              }}
              aria-label={t('filtersRemove', { name: text })}
            >
              <span className="truncate">{text}</span>
              <X className="h-4 w-4 shrink-0" aria-hidden="true" />
            </button>
          </li>
        );
      })}
      {entries.length > 1 && (
        <li>
          <button type="button" className="min-h-9 px-2 text-xs text-bambu-gray underline" onClick={() => onChange({})}>
            {t('filtersClearAll')}
          </button>
        </li>
      )}
    </ul>
  );
}

/**
 * Modal do filtro avançado da fonte ativa: folha de baixo no celular, caixa central no desktop.
 * Edita um rascunho; "Aplicar" grava e fecha, "Limpar" zera o rascunho. Aberto/fechado fica na URL (?filters=1)
 * para o voltar do Android fechar.
 */
export function FiltersModal({ title, schema, loading, error, value, onApply, onClose }: {
  title: string;
  schema: CatalogFilterSchema | undefined;
  loading: boolean;
  error: unknown;
  value: CatalogFilters;
  onApply: (filters: CatalogFilters) => void;
  onClose: () => void;
}) {
  const t = useCatalogT();
  const { i18n } = useTranslation();
  const [draft, setDraft] = useState<CatalogFilters>(value);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);
  const set = (id: string, v: CatalogFilterValue | null) =>
    setDraft((prev) => {
      const next = { ...prev };
      if (v == null) delete next[id];
      else next[id] = v;
      return next;
    });
  const count = countActive(draft);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 md:items-center md:p-6" onClick={onClose}>
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[88dvh] w-full flex-col rounded-t-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary outline-none md:max-h-[80vh] md:max-w-xl md:rounded-2xl"
      >
        <div className="flex items-center justify-between gap-2 border-b border-bambu-dark-tertiary px-4 py-2">
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <button type="button" className={`${controlClass} !border-0 !px-2`} onClick={onClose} aria-label={t('close')}>
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto overscroll-contain px-4 py-4">
          {loading && <p role="status" className="text-sm text-bambu-gray">{t('loading')}</p>}
          {!loading && error != null && <p role="alert" className="text-sm text-red-400">{t('loadError')}</p>}
          {schema && schema.groups.length === 0 && <p className="text-sm text-bambu-gray">{t('filtersEmpty')}</p>}
          {schema?.groups.map((g) => (
            <section key={g.id} aria-label={pickLabel(g.label, i18n.language)} className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-bambu-gray">{pickLabel(g.label, i18n.language)}</h3>
              {g.filters.map((f) => (
                <FilterField key={f.id} def={f} value={draft[f.id]} onChange={(v) => set(f.id, v)} language={i18n.language} />
              ))}
            </section>
          ))}
        </div>
        <div className="flex gap-2 border-t border-bambu-dark-tertiary px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <button type="button" className={`${controlClass} flex-1`} onClick={() => setDraft({})} disabled={!count}>
            {t('filtersClear')}
          </button>
          <button
            type="button"
            className={`${controlClass} flex-[2] !border-bambu-green bg-bambu-green font-semibold !text-black`}
            onClick={() => onApply(compact(draft))}
          >
            {t('filtersApply')}
            {count > 0 && ` (${count})`}
          </button>
        </div>
      </div>
    </div>
  );
}

function FilterField({ def, value, onChange, language }: {
  def: CatalogFilterDef;
  value: CatalogFilterValue | undefined;
  onChange: (v: CatalogFilterValue | null) => void;
  language: string;
}) {
  const t = useCatalogT();
  const name = pickLabel(def.label, language);
  const hint = def.hint ? <p className="text-xs text-bambu-gray">{pickLabel(def.hint, language)}</p> : null;
  const optLabel = (v: string) => pickLabel(def.options.find((o) => o.value === v)?.label, language) || v;

  if (def.type === 'bool') {
    return (
      <div className="space-y-1">
        <Switch id={`filter-${def.id}`} checked={value === true} onChange={(on) => onChange(on ? true : null)} label={name} />
        {hint}
      </div>
    );
  }
  if (def.type === 'range') {
    const [lo, hi] = Array.isArray(value) ? (value as [string | null, string | null]) : [null, null];
    const order = def.options.map((o) => o.value);
    const update = (nextLo: string | null, nextHi: string | null) =>
      onChange(nextLo || nextHi ? [nextLo, nextHi] : null);
    return (
      <fieldset className="space-y-1">
        <legend className="mb-1 text-sm font-medium text-white">{name}</legend>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-bambu-gray">
            {t('filtersFrom')}
            <select
              className={`${controlClass} mt-1 w-full bg-bambu-dark`}
              value={lo ?? ''}
              onChange={(e) => update(e.target.value || null, hi && e.target.value && order.indexOf(e.target.value) >= order.indexOf(hi) ? null : hi)}
            >
              <option value="">{t('filtersNoLimit')}</option>
              {def.options.map((o) => (
                <option key={o.value} value={o.value}>{optLabel(o.value)}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-bambu-gray">
            {t('filtersTo')}
            <select
              className={`${controlClass} mt-1 w-full bg-bambu-dark`}
              value={hi ?? ''}
              disabled={def.requires_min && !lo}
              onChange={(e) => update(lo, e.target.value || null)}
            >
              <option value="">{t('filtersNoLimit')}</option>
              {def.options.map((o) => (
                <option key={o.value} value={o.value} disabled={!!lo && order.indexOf(o.value) <= order.indexOf(lo)}>
                  {optLabel(o.value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {hint}
      </fieldset>
    );
  }
  const multi = def.type === 'multi';
  const selected = multi ? (Array.isArray(value) ? (value as string[]) : []) : typeof value === 'string' ? [value] : [];
  const toggle = (v: string) => {
    if (multi) {
      const next = selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v];
      onChange(next.length ? next : null);
    } else onChange(selected[0] === v ? null : v);
  };
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-sm font-medium text-white">{name}</legend>
      <div className="flex flex-wrap gap-2" role={multi ? 'group' : 'radiogroup'} aria-label={name}>
        {!multi && (
          <button type="button" role="radio" aria-checked={selected.length === 0} className={chipClass(selected.length === 0)} onClick={() => onChange(null)}>
            {t('filtersAny')}
          </button>
        )}
        {def.options.map((o) => {
          const on = selected.includes(o.value);
          return multi ? (
            <button key={o.value} type="button" aria-pressed={on} className={chipClass(on)} onClick={() => toggle(o.value)}>
              {pickLabel(o.label, language)}
            </button>
          ) : (
            <button key={o.value} type="button" role="radio" aria-checked={on} className={chipClass(on)} onClick={() => toggle(o.value)}>
              {pickLabel(o.label, language)}
            </button>
          );
        })}
      </div>
      {hint}
    </fieldset>
  );
}
