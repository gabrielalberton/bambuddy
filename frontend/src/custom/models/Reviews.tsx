import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { CheckCircle2, Loader2, MessageSquare, Star, ThumbsUp, XCircle, Zap } from 'lucide-react';
import { catalogApi } from './api';
import { useCatalogT } from './i18n';
import { controlClass } from './constants';
import { CatalogError } from './shared';
import type { CatalogRating, CatalogReview, CatalogReviewCapabilities, CatalogReviewKind, CatalogReviewSort, CatalogSourceId } from './types';
import { compactNumber, isoDate } from './format';

/** Estrelas de 0-5 com preenchimento parcial (4,9 → quase cinco cheias). */
export function Stars({ value, size = 'h-4 w-4' }: { value: number; size?: string }) {
  return (
    <span className="inline-flex shrink-0 items-center" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((i) => {
        const fill = Math.max(0, Math.min(1, value - i));
        return (
          <span key={i} className={`relative inline-block ${size}`}>
            <Star className={`absolute inset-0 ${size} text-bambu-dark-tertiary`} fill="currentColor" strokeWidth={0} />
            {fill > 0 && (
              <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
                <Star className={`${size} text-amber-400`} fill="currentColor" strokeWidth={0} />
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

/** "★★★★★ 4.9 (942)" perto do título; toque leva à seção de avaliações. */
export function RatingSummary({ rating, onClick }: { rating: CatalogRating; onClick?: () => void }) {
  const t = useCatalogT();
  if (rating.average == null || rating.count <= 0) {
    return <span className="text-sm text-bambu-gray">{t('noRatings')}</span>;
  }
  const average = rating.average.toFixed(1);
  const content = (
    <>
      <Stars value={rating.average} />
      <span className="font-semibold text-white">{average}</span>
      <span className="text-bambu-gray">({compactNumber(rating.count)})</span>
    </>
  );
  const aria = t('ratingAria', { average, count: rating.count });
  return onClick ? (
    <button type="button" onClick={onClick} aria-label={aria} className="inline-flex min-h-11 items-center gap-1.5 text-sm md:min-h-0">
      {content}
    </button>
  ) : (
    <span role="img" aria-label={aria} className="inline-flex items-center gap-1.5 text-sm">
      {content}
    </span>
  );
}

/**
 * Seção "Avaliações": só busca quando aparece na tela (ou ao tocar no resumo de
 * estrelas), página de 10 com "Ver mais". Texto sempre como texto puro.
 */
export function ReviewsSection({
  source,
  modelId,
  capabilities,
  rating,
  forceLoad = false,
}: {
  source: CatalogSourceId;
  modelId: string;
  capabilities: CatalogReviewCapabilities;
  rating: CatalogRating | null | undefined;
  forceLoad?: boolean;
}) {
  const t = useCatalogT();
  const ref = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  const [kind, setKind] = useState<CatalogReviewKind>(capabilities.kinds[0]);
  const [sort, setSort] = useState<CatalogReviewSort>(capabilities.sorts[0]);

  useEffect(() => {
    if (seen) return;
    const node = ref.current;
    if (!node || typeof IntersectionObserver === 'undefined') {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setSeen(true);
      },
      { rootMargin: '200px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen]);

  const enabled = seen || forceLoad;
  const query = useInfiniteQuery({
    queryKey: ['custom-models', source, 'reviews', modelId, kind, sort],
    queryFn: ({ pageParam, signal }) => catalogApi.reviews(source, modelId, kind, sort, pageParam, signal),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.has_more ? last.page + 1 : undefined),
    enabled,
    staleTime: 120_000,
    retry: false,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? null;
  const nextPageError: unknown = query.error;

  return (
    <section ref={ref} id="catalog-reviews" aria-labelledby="catalog-reviews-title" className="scroll-mt-4 space-y-3 rounded-xl border border-bambu-dark-tertiary p-3 md:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="catalog-reviews-title" className="text-base font-semibold text-white">{t('reviews')}</h3>
        {rating && <RatingSummary rating={rating} />}
      </div>

      {(capabilities.kinds.length > 1 || capabilities.sorts.length > 1) && (
        <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 md:mx-0 md:px-0">
          {capabilities.kinds.length > 1 &&
            capabilities.kinds.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`${controlClass} shrink-0 rounded-full ${kind === k ? '!border-bambu-green bg-bambu-green/15 !text-bambu-green' : ''}`}
              >
                {t(`reviewsKind_${k}`)}
                {kind === k && total != null && <span className="text-xs opacity-80">{compactNumber(total)}</span>}
              </button>
            ))}
          {capabilities.sorts.length > 1 && (
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as CatalogReviewSort)}
              aria-label={t('sort')}
              className={`${controlClass} ml-auto shrink-0 bg-bambu-dark-secondary`}
            >
              {capabilities.sorts.map((s) => (
                <option key={s} value={s}>{t(`reviewsSort_${s}`)}</option>
              ))}
            </select>
          )}
        </div>
      )}

      {!enabled ? (
        <p className="text-sm text-bambu-gray">{t('reviewsLoadOnScroll')}</p>
      ) : query.isPending ? (
        <p role="status" className="flex items-center gap-2 text-sm text-bambu-gray">
          <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
          {t('loading')}
        </p>
      ) : query.isError ? (
        <CatalogError error={query.error} onRetry={() => void query.refetch()} compact />
      ) : items.length === 0 ? (
        <p className="text-sm text-bambu-gray">{t(kind === 'ratings' ? 'reviewsEmpty' : 'commentsEmpty')}</p>
      ) : (
        <>
          <ul className="divide-y divide-bambu-dark-tertiary">
            {items.map((item) => (
              <ReviewItem key={item.id} source={source} item={item} />
            ))}
          </ul>
          {query.hasNextPage && (
            <button type="button" className={`${controlClass} w-full`} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
              {query.isFetchingNextPage && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />}
              {t('loadMore')}
            </button>
          )}
          {query.isFetchNextPageError && <CatalogError error={nextPageError} compact />}
        </>
      )}
    </section>
  );
}

function Avatar({ name }: { name: string }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-bambu-dark-tertiary text-sm font-semibold uppercase text-white" aria-hidden="true">
      {Array.from(name.trim())[0] ?? '?'}
    </span>
  );
}

function ReviewItem({ source, item, nested = false }: { source: CatalogSourceId; item: CatalogReview; nested?: boolean }) {
  const t = useCatalogT();
  return (
    <li className={nested ? 'flex gap-2 pt-2' : 'flex gap-3 py-3'}>
      {!nested && <Avatar name={item.author} />}
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
          <span className="font-medium text-white break-all">{item.author}</span>
          {item.rating != null && (
            <span role="img" aria-label={t('ratingAria', { average: item.rating, count: 1 })}>
              <Stars value={item.rating} size="h-3.5 w-3.5" />
            </span>
          )}
          {item.created && <time dateTime={item.created} className="text-xs text-bambu-gray">{isoDate(item.created)}</time>}
          {item.boosted && (
            <span className="inline-flex items-center gap-0.5 rounded bg-amber-400/10 px-1.5 py-0.5 text-xs text-amber-400">
              <Zap className="h-3 w-3" aria-hidden="true" />
              {t('boosted')}
            </span>
          )}
        </div>
        {(item.profile || item.printed != null) && (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-bambu-gray">
            {item.printed === true && (
              <span className="inline-flex items-center gap-1 text-bambu-green"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />{t('printedOk')}</span>
            )}
            {item.printed === false && (
              <span className="inline-flex items-center gap-1 text-yellow-400"><XCircle className="h-3.5 w-3.5" aria-hidden="true" />{t('printedFail')}</span>
            )}
            {item.profile?.name && <span className="min-w-0 break-words">{t('profileUsed', { name: item.profile.name })}</span>}
          </p>
        )}
        {item.issues.length > 0 && (
          <p className="flex flex-wrap gap-1">
            {item.issues.map((issue) => (
              <span key={issue} className="rounded bg-yellow-500/10 px-1.5 py-0.5 text-xs text-yellow-400">{issue}</span>
            ))}
          </p>
        )}
        {item.text && <p className="whitespace-pre-line break-words text-sm text-bambu-gray">{item.text}</p>}
        {item.images.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {item.images.map((img, index) => (
              <a
                key={img.thumb}
                href={catalogApi.thumbnailUrl(source, img.full)}
                target="_blank"
                rel="noopener noreferrer"
                className="h-20 w-20 shrink-0 overflow-hidden rounded-lg bg-bambu-dark-secondary"
              >
                <img
                  src={catalogApi.thumbnailUrl(source, img.thumb)}
                  alt={t('reviewImage', { index: index + 1 })}
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
                  className="h-full w-full object-cover"
                />
              </a>
            ))}
          </div>
        )}
        {(item.likes || item.replies) ? (
          <p className="flex gap-4 text-xs text-bambu-gray">
            {item.likes ? (
              <span className="inline-flex items-center gap-1" aria-label={t('likes', { count: item.likes })}>
                <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />{compactNumber(item.likes)}
              </span>
            ) : null}
            {item.replies ? (
              <span className="inline-flex items-center gap-1" aria-label={t('replies', { count: item.replies })}>
                <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />{compactNumber(item.replies)}
              </span>
            ) : null}
          </p>
        ) : null}
        {item.reply_preview.length > 0 && (
          <ul className="border-l-2 border-bambu-dark-tertiary pl-3">
            {item.reply_preview.map((reply) => (
              <ReviewItem key={reply.id} source={source} item={reply} nested />
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}
