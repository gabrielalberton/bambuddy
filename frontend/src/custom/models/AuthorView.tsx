import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { catalogApi } from './api';
import { useCatalogT } from './i18n';
import { controlClass, sourceName } from './constants';
import { CatalogError } from './shared';
import { ModelCard } from './ModelCard';
import type { CatalogCard, CatalogMineKind, CatalogSourceId } from './types';

const PAGE = 24;

/**
 * Lista de modelos fora da busca: catálogo de um autor (link interno a partir do nome do autor no detalhe) ou, com
 * `mine`, os curtidos/salvos do próprio usuário no MakerWorld (credencial Bambu Cloud salva).
 */
export function AuthorView({ source, authorId, name, onBack, onOpen, mine, onMine }: {
  source: CatalogSourceId;
  authorId: string;
  name: string | null;
  onBack: () => void;
  onOpen: (card: CatalogCard) => void;
  mine?: CatalogMineKind;
  onMine?: (kind: CatalogMineKind) => void;
}) {
  const t = useCatalogT();
  const compact = useMemo(() => new Intl.NumberFormat(undefined, { notation: 'compact' }), []);
  const query = useInfiniteQuery({
    queryKey: mine ? ['custom-models', 'makerworld', 'mine', mine] : ['custom-models', source, 'author', authorId],
    queryFn: ({ pageParam, signal }) =>
      mine ? catalogApi.mine(mine, pageParam, PAGE, signal) : catalogApi.author(source, authorId, pageParam, PAGE, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * PAGE : undefined),
    staleTime: 120_000,
    retry: false,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? null;
  const title = mine ? t('mine') : query.data?.pages[0]?.author.name || name || authorId;
  const nextError: unknown = query.error;

  return (
    <div className="space-y-4 pb-2">
      <div className="flex items-center justify-between gap-3">
        <button type="button" className={controlClass} onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t('back')}
        </button>
        <span className="truncate text-sm text-bambu-green">{sourceName[source]}</span>
      </div>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="break-words text-xl font-bold text-white md:text-3xl">{title}</h2>
        {total != null && <span className="text-sm text-bambu-gray">{t('results', { count: compact.format(total) })}</span>}
      </header>
      {mine && onMine && (
        <div role="tablist" aria-label={t('mine')} className="inline-flex rounded-lg bg-bambu-dark-secondary p-1">
          {(['likes', 'saved'] as const).map((kind) => (
            <button
              key={kind}
              type="button"
              role="tab"
              aria-selected={mine === kind}
              onClick={() => onMine(kind)}
              className={`min-h-10 rounded-md px-4 text-sm ${mine === kind ? 'bg-bambu-green text-white' : 'text-bambu-gray hover:text-white'}`}
            >
              {t(kind === 'likes' ? 'mineLikes' : 'mineSaved')}
            </button>
          ))}
        </div>
      )}
      {query.isPending ? (
        <p role="status" className="flex items-center gap-2 text-sm text-bambu-gray">
          <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
          {t('loading')}
        </p>
      ) : query.isError && items.length === 0 ? (
        <CatalogError error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            {items.map((card) => (
              <li key={`${card.provider}:${card.id}`} className="min-w-0">
                <ModelCard card={card} compact={compact} onOpen={onOpen} />
              </li>
            ))}
          </ul>
          {query.hasNextPage && (
            <button type="button" className={`${controlClass} w-full`} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
              {query.isFetchingNextPage && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />}
              {t('loadMore')}
            </button>
          )}
          {query.isFetchNextPageError && <CatalogError error={nextError} compact />}
        </>
      )}
    </div>
  );
}
