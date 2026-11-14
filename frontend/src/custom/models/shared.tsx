import { useState } from 'react';
import { AlertCircle, Box, RefreshCw } from 'lucide-react';
import { ApiError } from '../../api/client';
import { catalogApi } from './api';
import { useCatalogT } from './i18n';
import { controlClass } from './constants';
import type { CatalogSourceId } from './types';

export function CatalogImage(props: { source: CatalogSourceId; url: string | null; alt: string; className?: string }) {
  // Nova URL = novo estado de erro.
  return <ImageInner key={props.url ?? ''} {...props} />;
}

function ImageInner({ source, url, alt, className }: { source: CatalogSourceId; url: string | null; alt: string; className?: string }) {
  const t = useCatalogT();
  const [failed, setFailed] = useState(false);
  if (url && !failed) {
    return (
      <img
        src={catalogApi.thumbnailUrl(source, url)}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className={className}
      />
    );
  }
  return (
    <div className="w-full h-full min-h-24 flex flex-col items-center justify-center gap-2 text-bambu-gray" role={alt ? 'img' : undefined} aria-label={alt || undefined}>
      <Box className="h-8 w-8" aria-hidden="true" />
      <span className="text-xs">{t('noImage')}</span>
    </div>
  );
}

export function CatalogError({ error, onRetry, compact = false }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const t = useCatalogT();
  const auth = error instanceof ApiError && (error.status === 401 || error.status === 403);
  return (
    <div role="alert" className={`rounded-lg border border-red-500/30 bg-red-500/5 text-sm ${compact ? 'p-3' : 'p-4'}`}>
      <div className="flex items-start gap-2">
        <AlertCircle className="h-5 w-5 shrink-0 text-red-400" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-medium text-white">{t(auth ? 'authError' : 'loadError')}</p>
          {error instanceof Error && <p className="text-bambu-gray mt-1 break-words">{error.message}</p>}
        </div>
      </div>
      {onRetry && (
        <button type="button" className={`${controlClass} mt-3`} onClick={onRetry}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {t('retry')}
        </button>
      )}
    </div>
  );
}

/** Chave liga/desliga grande (toque). */
export function Switch({ checked, onChange, label, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; id: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`inline-flex min-h-11 items-center gap-3 rounded-full border px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-bambu-green ${
        checked ? 'border-bambu-green bg-bambu-green/15 text-bambu-green' : 'border-bambu-dark-tertiary text-bambu-gray'
      }`}
    >
      <span className={`relative inline-block h-6 w-10 shrink-0 rounded-full transition-colors ${checked ? 'bg-bambu-green' : 'bg-bambu-dark-tertiary'}`} aria-hidden="true">
        <span className={`absolute top-1 h-4 w-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : 'translate-x-1'}`} />
      </span>
      {label}
    </button>
  );
}
