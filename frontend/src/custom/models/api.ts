import { ApiError, getAuthToken } from '../../api/client';
import type {
  CatalogAuthorResponse,
  CatalogMineKind,
  CatalogBrowseParams,
  CatalogBrowseResponse,
  CatalogDetail,
  CatalogFilterSchema,
  CatalogReviewKind,
  CatalogReviewSort,
  CatalogReviewsResponse,
  CatalogSavedFile,
  CatalogSourceId,
  CatalogSourcesResponse,
} from './types';

const BASE = '/api/v1/custom/models';

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${BASE}${path}`, { ...init, headers, cache: 'no-store', credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = (body as { detail?: unknown }).detail;
    const message = typeof detail === 'string' ? detail : `HTTP ${response.status}`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

function modelsQuery(params: URLSearchParams, models: string[]): URLSearchParams {
  for (const model of models) params.append('printer_models', model);
  return params;
}

export const catalogApi = {
  sources: (printerModels: string[], signal?: AbortSignal) =>
    call<CatalogSourcesResponse>(`/sources?${modelsQuery(new URLSearchParams(), printerModels)}`, { signal }),
  browse: (source: CatalogSourceId, p: CatalogBrowseParams, signal?: AbortSignal) => {
    const params = new URLSearchParams({
      query: p.query,
      sort: p.sort,
      offset: String(p.offset),
      limit: String(p.limit),
      printer_filter: String(p.printerFilter),
      author_printer: String(p.authorPrinter),
    });
    if (p.category) params.set('category', p.category);
    if (p.filters && Object.keys(p.filters).length) params.set('filters', JSON.stringify(p.filters));
    return call<CatalogBrowseResponse>(`/${source}/browse?${modelsQuery(params, p.printerModels)}`, { signal });
  },
  filters: (source: CatalogSourceId, signal?: AbortSignal) => call<CatalogFilterSchema>(`/${source}/filters`, { signal }),
  categories: (source: CatalogSourceId, signal?: AbortSignal) =>
    call<{ id: string; name: string }[]>(`/${source}/categories`, { signal }),
  detail: (source: CatalogSourceId, id: string, printerModels: string[], signal?: AbortSignal) =>
    call<CatalogDetail>(`/${source}/${encodeURIComponent(id)}?${modelsQuery(new URLSearchParams(), printerModels)}`, {
      signal,
    }),
  author: (source: CatalogSourceId, authorId: string, offset: number, limit: number, signal?: AbortSignal) =>
    call<CatalogAuthorResponse>(
      `/${source}/author/${encodeURIComponent(authorId)}?${new URLSearchParams({ offset: String(offset), limit: String(limit) })}`,
      { signal },
    ),
  mine: (kind: CatalogMineKind, offset: number, limit: number, signal?: AbortSignal) =>
    call<CatalogAuthorResponse>(`/makerworld/mine/${kind}?${new URLSearchParams({ offset: String(offset), limit: String(limit) })}`, { signal }),
  reviews: (source: CatalogSourceId, id: string, kind: CatalogReviewKind, sort: CatalogReviewSort, page: number, signal?: AbortSignal) =>
    call<CatalogReviewsResponse>(
      `/${source}/${encodeURIComponent(id)}/reviews?${new URLSearchParams({ kind, sort, page: String(page) })}`,
      { signal },
    ),
  save: (source: CatalogSourceId, id: string, fileId: string, folderId: number | null) =>
    call<CatalogSavedFile>(`/${source}/${encodeURIComponent(id)}/save`, {
      method: 'POST',
      body: JSON.stringify({ file_id: fileId, folder_id: folderId }),
    }),
  thumbnailUrl: (source: CatalogSourceId, url: string) => `${BASE}/${source}/thumbnail?url=${encodeURIComponent(url)}`,
};
