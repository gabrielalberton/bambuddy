import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { catalogApi } from './api';
import { useCatalogT } from './i18n';
import { ModelDetail } from './ModelDetail';
import { MakerworldImportButton } from './ImportModal';
import { controlClass, sourceName } from './constants';
import { CatalogError, Switch } from './shared';
import { ModelCard } from './ModelCard';
import { AuthorView } from './AuthorView';
import type { CatalogCard, CatalogSort, CatalogSourceId, CatalogSourceInfo } from './types';
import { usePrinterModels } from './usePrinterModels';
import { AUTHOR_PRINTER_KEY, PRINTER_FILTER_KEY, readBool, writeBool } from './utils';

const PAGE_SIZE = 24;
const SORTS: CatalogSort[] = ['trending', 'popular', 'newest', 'relevance'];

/**
 * Catálogo de modelos (estilo "MakerWorld" do Bambu Handy), pensado primeiro
 * para o PWA no celular: busca no topo, chips de fonte roláveis, chave grande
 * do filtro da impressora, grade de 2 colunas.
 *
 * Estado na URL (?tab=catalog&src=&q=&sort=&cat=&<fonte>Off=&model=&msrc=):
 * o "voltar" do Android fecha o detalhe e volta à página anterior.
 */
export function ModelCatalog() {
  const t = useCatalogT();
  const { hasPermission, hasAnyPermission } = useAuth();
  const printer = usePrinterModels();
  const [params, setParams] = useSearchParams();
  const [printerFilter, setPrinterFilterState] = useState(() => readBool(PRINTER_FILTER_KEY, true));
  const [authorPrinter, setAuthorPrinterState] = useState(() => readBool(AUTHOR_PRINTER_KEY, false));
  const setPrinterFilter = (value: boolean) => {
    setPrinterFilterState(value);
    writeBool(PRINTER_FILTER_KEY, value);
  };
  const setAuthorPrinter = (value: boolean) => {
    setAuthorPrinterState(value);
    writeBool(AUTHOR_PRINTER_KEY, value);
  };

  const sourcesQuery = useQuery({
    queryKey: ['custom-models', 'sources', printer.models],
    queryFn: ({ signal }) => catalogApi.sources(printer.models, signal),
    staleTime: 300_000,
    retry: false,
  });
  const allowed = (s: CatalogSourceInfo) =>
    s.permission === 'makerworld'
      ? hasPermission('makerworld:view')
      : hasAnyPermission('library:read_own', 'library:read_all', 'library:read');
  const sources = (sourcesQuery.data?.sources ?? []).filter(allowed);
  const enabled = sources.filter((s) => s.enabled);

  const requested = params.get('src');
  const current = enabled.find((s) => s.id === requested)?.id ?? 'all';
  const visible = current === 'all' ? enabled : enabled.filter((s) => s.id === current);
  const query = params.get('q') ?? '';
  const sort = SORTS.find((s) => s === params.get('sort')) ?? (query ? 'relevance' : 'trending');
  const category = current === 'all' ? '' : params.get('cat') ?? '';
  const model = params.get('model');
  const modelSource = params.get('msrc') as CatalogSourceId | null;
  const author = params.get('author');
  const authorSource = params.get('asrc') as CatalogSourceId | null;
  const [input, setInput] = useState(query);

  useEffect(() => {
    setInput(query);
  }, [query]);
  // Busca só ao tocar na lupa (ou Enter no teclado); limpar o campo volta para a lista na hora.
  const submitSearch = (value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value.trim()) next.set('q', value.trim());
        else next.delete('q');
        for (const key of Array.from(next.keys())) if (key.endsWith('Off')) next.delete(key);
        return next;
      },
      { replace: true },
    );

  const change = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', 'catalog');
        if (value) next.set(key, value);
        else next.delete(key);
        if (key === 'src') next.delete('cat');
        for (const k of Array.from(next.keys())) if (k.endsWith('Off')) next.delete(k);
        return next;
      },
      { replace: true },
    );
  // push (não replace): o "voltar" do celular fecha o detalhe.
  const openModel = (card: Pick<CatalogCard, 'id' | 'provider'>) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', 'catalog');
      next.set('model', card.id);
      next.set('msrc', card.provider);
      return next;
    });
  // links internos: autor (catálogo dele) e outro modelo citado na descrição — push, o "voltar" retorna
  const openAuthor = (src: CatalogSourceId, id: string, name: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', 'catalog');
      next.delete('model');
      next.delete('msrc');
      next.set('author', id);
      next.set('asrc', src);
      next.set('aname', name);
      return next;
    });
  // Voltar = histórico (modelo -> autor -> modelo...); aberto direto por link/notificação, só fecha.
  const goBack = (close: () => void) => ((window.history.state as { idx?: number } | null)?.idx ?? 0) > 0 ? window.history.back() : close();
  const closeAuthor = () =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('author');
      next.delete('asrc');
      next.delete('aname');
      return next;
    });
  const closeModel = () =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('model');
      next.delete('msrc');
      return next;
    });

  if (model && modelSource && enabled.some((s) => s.id === modelSource)) {
    return (
      <ModelDetail
        key={`${modelSource}:${model}`}
        source={modelSource}
        id={model}
        printer={printer}
        onBack={() => goBack(closeModel)}
        onOpenModel={(src, mid) => openModel({ id: mid, provider: src })}
        onOpenAuthor={openAuthor}
      />
    );
  }
  if (author && authorSource && enabled.some((s) => s.id === authorSource)) {
    return (
      <AuthorView
        key={`${authorSource}:${author}`}
        source={authorSource}
        authorId={author}
        name={params.get('aname')}
        onBack={() => goBack(closeAuthor)}
        onOpen={openModel}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <form
          role="search"
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submitSearch(input);
            (document.activeElement as HTMLElement | null)?.blur?.();
          }}
        >
          <select
            value={current}
            onChange={(e) => change('src', e.target.value === 'all' ? '' : e.target.value)}
            aria-label={t('sources')}
            className={`${controlClass} w-28 shrink-0 truncate bg-bambu-dark-secondary px-2 md:w-40`}
          >
            {enabled.length > 1 && <option value="all">{t('allSources')}</option>}
            {enabled.map((s) => (
              <option key={s.id} value={s.id}>{sourceName[s.id]}</option>
            ))}
            {sources
              .filter((s) => !s.enabled)
              .map((s) => (
                <option key={s.id} value={s.id} disabled title={s.disabled_reason ?? ''}>
                  {s.name} · {t('sourceDisabledHint')}
                </option>
              ))}
          </select>
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t('search')}</span>
            <input
              type="search"
              inputMode="search"
              enterKeyHint="search"
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                if (!e.target.value && query) submitSearch('');
              }}
              placeholder={t('searchPlaceholder')}
              className="w-full min-h-11 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary px-3 text-base text-white placeholder:text-bambu-gray focus:border-bambu-green focus:outline-none"
            />
          </label>
          <button type="submit" className={`${controlClass} shrink-0 !px-3`} aria-label={t('search')} title={t('search')}>
            <Search className="h-5 w-5" aria-hidden="true" />
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-2">
          <Switch id="catalog-printer-filter" checked={printerFilter} onChange={setPrinterFilter} label={t('printerFilter', { printer: printer.label })} />
          <label className="flex min-w-0 items-center gap-2 text-sm text-bambu-gray">
            <span className="sr-only md:not-sr-only">{t('sort')}</span>
            <select value={sort} onChange={(e) => change('sort', e.target.value)} className={`${controlClass} bg-bambu-dark-secondary`} aria-label={t('sort')}>
              {SORTS.map((s) => (
                <option key={s} value={s}>
                  {t(s === 'newest' && current === 'makerworld' ? 'recentMakerworld' : s)}
                </option>
              ))}
            </select>
          </label>
          {current !== 'all' && <Categories source={current} value={category} onChange={(v) => change('cat', v)} />}
          <MakerworldImportButton />
        </div>
      </div>

      {sourcesQuery.isError && <CatalogError error={sourcesQuery.error} onRetry={() => void sourcesQuery.refetch()} />}
      {sourcesQuery.isPending && <p role="status" className="text-sm text-bambu-gray">{t('loading')}</p>}

      {visible.map((s) => (
        <SourceResults
          key={`${s.id}:${query}:${sort}:${category}:${printerFilter}:${authorPrinter}:${printer.label}`}
          source={s}
          single={visible.length === 1}
          query={query}
          sort={sort}
          category={category}
          printerModels={printer.models}
          printerLabel={printer.label}
          printerFilter={printerFilter}
          authorPrinter={authorPrinter}
          onAuthorPrinter={setAuthorPrinter}
          onOpen={openModel}
        />
      ))}
    </div>
  );
}

function Categories({ source, value, onChange }: { source: CatalogSourceId; value: string; onChange: (v: string) => void }) {
  const t = useCatalogT();
  const categories = useQuery({
    queryKey: ['custom-models', source, 'categories'],
    queryFn: ({ signal }) => catalogApi.categories(source, signal),
    staleTime: 3_600_000,
    retry: false,
  });
  if (categories.isError || (categories.data && categories.data.length === 0)) return null;
  return (
    <select
      aria-label={t('category')}
      className={`${controlClass} max-w-[60vw] bg-bambu-dark-secondary md:max-w-64`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={categories.isPending}
    >
      <option value="">{t('allCategories')}</option>
      {value && !categories.data?.some((c) => c.id === value) && <option value={value}>{value}</option>}
      {categories.data?.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

function FilterNote({ source, printerLabel, printerFilter, applied, authorPrinter, onAuthorPrinter }: {
  source: CatalogSourceInfo;
  printerLabel: string;
  printerFilter: boolean;
  applied: boolean | undefined;
  authorPrinter: boolean;
  onAuthorPrinter: (v: boolean) => void;
}) {
  const t = useCatalogT();
  if (!printerFilter) return <p className="text-xs text-bambu-gray">{t('filterNotApplied')}</p>;
  // filtro aplicado pelo próprio MakerWorld: nada a avisar (a chave "Só para minha A1" já diz)
  if (source.printer_filter === 'server') return applied === false ? <p className="text-xs text-bambu-gray">{t('filterNotApplied')}</p> : null;
  if (source.printer_filter === 'author_printer')
    return (
      <div className="space-y-1 text-xs">
        <p className="text-yellow-400/90">{authorPrinter ? t('filterAuthorApplied', { printer: printerLabel }) : t('filterNaPrintables', { printer: printerLabel })}</p>
        <label className="inline-flex min-h-11 items-center gap-2 text-bambu-gray">
          <input type="checkbox" className="h-5 w-5 accent-bambu-green" checked={authorPrinter} onChange={(e) => onAuthorPrinter(e.target.checked)} />
          {t('filterAuthorPrinter', { printer: printerLabel })}
        </label>
      </div>
    );
  return <p className="text-xs text-yellow-400/90">{t('filterNaThingiverse', { printer: printerLabel })}</p>;
}

function SourceResults({ source, single, query, sort, category, printerModels, printerLabel, printerFilter, authorPrinter, onAuthorPrinter, onOpen }: {
  source: CatalogSourceInfo;
  /** só uma fonte na tela: sem título (a fonte já está no seletor ao lado da busca) */
  single: boolean;
  query: string;
  sort: CatalogSort;
  category: string;
  printerModels: string[];
  printerLabel: string;
  printerFilter: boolean;
  authorPrinter: boolean;
  onAuthorPrinter: (v: boolean) => void;
  onOpen: (card: CatalogCard) => void;
}) {
  const t = useCatalogT();
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get(`${source.id}Off`) ?? 0);
  const offset = Number.isSafeInteger(raw) && raw >= 0 ? raw : 0;
  const effectiveSort = source.sorts.includes(sort) ? sort : source.sorts[0];
  const results = useQuery({
    queryKey: ['custom-models', source.id, 'browse', query, effectiveSort, category, offset, printerModels, printerFilter, authorPrinter],
    queryFn: ({ signal }) =>
      catalogApi.browse(
        source.id,
        { query, sort: effectiveSort, category, offset, limit: PAGE_SIZE, printerModels, printerFilter, authorPrinter: source.id === 'printables' && authorPrinter },
        signal,
      ),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
  const page = (next: number) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set(`${source.id}Off`, String(next));
      return p;
    });
  const compact = useMemo(() => new Intl.NumberFormat(undefined, { notation: 'compact' }), []);
  const total = results.data?.total;
  const heading = `catalog-${source.id}`;

  return (
    <section aria-labelledby={heading} className="space-y-3">
      <div className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 ${single ? 'justify-end' : 'justify-between'}`}>
        <h2 id={heading} className={single ? 'sr-only' : 'text-lg font-semibold text-white'}>
          {source.name}
          <span className="ml-2 text-sm font-normal text-bambu-gray">
            {t(effectiveSort === 'newest' && source.id === 'makerworld' ? 'recentMakerworld' : effectiveSort)}
          </span>
        </h2>
        {total != null && <span className="text-sm text-bambu-gray">{total >= 10000 ? t('resultsMany') : t('results', { count: compact.format(total) })}</span>}
      </div>
      <FilterNote
        source={source}
        printerLabel={printerLabel}
        printerFilter={printerFilter}
        applied={results.data?.printer_filter.applied}
        authorPrinter={authorPrinter}
        onAuthorPrinter={onAuthorPrinter}
      />
      {results.isPending ? (
        <div role="status" aria-label={t('loading')} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="overflow-hidden rounded-xl bg-bambu-dark-secondary motion-safe:animate-pulse">
              <div className="aspect-square bg-bambu-dark-tertiary" />
              <div className="m-3 h-10 rounded bg-bambu-dark-tertiary" />
            </div>
          ))}
        </div>
      ) : results.isError ? (
        <CatalogError error={results.error} onRetry={() => void results.refetch()} />
      ) : results.data.items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-bambu-dark-tertiary p-6 text-center">
          <Search className="mx-auto mb-2 h-7 w-7 text-bambu-gray" aria-hidden="true" />
          <p className="font-medium text-white">{t('empty')}</p>
          <p className="mt-1 text-sm text-bambu-gray">{t('emptyHint')}</p>
        </div>
      ) : (
        <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
          {results.data.items.map((card) => (
            <li key={`${card.provider}:${card.id}`} className="min-w-0">
<ModelCard card={card} compact={compact} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center justify-between gap-2">
        <button type="button" className={controlClass} onClick={() => page(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0 || results.isFetching}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {t('previous')}
        </button>
        <span className="text-sm text-bambu-gray" aria-live="polite">
          {t('page', { page: Math.floor(offset / PAGE_SIZE) + 1 })}
        </span>
        <button type="button" className={controlClass} onClick={() => page(offset + PAGE_SIZE)} disabled={!results.data?.has_more || results.isFetching || results.isError}>
          {t('next')}
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
