export type CatalogSourceId = 'makerworld' | 'printables' | 'thingiverse';
export type CatalogSort = 'trending' | 'popular' | 'newest' | 'relevance';
export type PrinterMatch = 'native' | 'compatible' | 'unknown' | 'other';
export type PrinterFilterMode = 'server' | 'author_printer' | 'none';

export interface CatalogSourceInfo {
  id: CatalogSourceId;
  name: string;
  enabled: boolean;
  disabled_reason: string | null;
  permission: 'makerworld' | 'library';
  sorts: CatalogSort[];
  printer_filter: PrinterFilterMode;
  printer_filter_note: string;
}

export interface CatalogSourcesResponse {
  sources: CatalogSourceInfo[];
  printer_models: string[];
  makerworld_codes: string[];
  printables_printer_ids: number[];
}

export interface CatalogCard {
  provider: CatalogSourceId;
  id: string;
  title: string;
  url: string;
  creator: string;
  creator_id?: string | null;
  thumbnail: string | null;
  downloads: number | null;
  likes: number | null;
}

export interface CatalogBrowseResponse {
  items: CatalogCard[];
  total: number | null;
  has_more: boolean;
  sort: CatalogSort;
  printer_models: string[];
  printer_filter: { mode: PrinterFilterMode; applied: boolean; codes?: string[]; printer_ids?: number[] };
}

export interface CatalogFile {
  id: string;
  name: string;
  format: string;
  size: number | null;
  sliceable: boolean;
  printer_match: PrinterMatch;
  printer: string | null;
  metadata: Record<string, unknown>;
}

export interface CatalogDetail extends CatalogCard {
  description_html: string;
  images: string[];
  license: string | null;
  files: CatalogFile[];
  preselect_file_id: string | null;
  printer_models: string[];
  metadata: Record<string, unknown>;
  /** Nota média (1-5) e quantidade de avaliações; null = a fonte não tem notas. */
  rating?: CatalogRating | null;
  stats?: CatalogStats;
  /** null/ausente = a fonte não expõe avaliações/comentários. */
  reviews?: CatalogReviewCapabilities | null;
}

export interface CatalogRating {
  average: number | null;
  count: number;
}

export interface CatalogStats {
  downloads?: number | null;
  prints?: number | null;
  likes?: number | null;
  collections?: number | null;
  boosts?: number | null;
  makes?: number | null;
  published?: string | null;
}

export type CatalogReviewKind = 'ratings' | 'comments' | 'all';
export type CatalogReviewSort = 'top' | 'newest';

export interface CatalogReviewCapabilities {
  kinds: CatalogReviewKind[];
  sorts: CatalogReviewSort[];
  page_size: number;
}

export interface CatalogReviewImage {
  thumb: string;
  full: string;
}

export interface CatalogReview {
  id: string;
  kind: 'rating' | 'comment';
  author: string;
  rating: number | null;
  text: string;
  created: string | null;
  likes: number | null;
  replies: number | null;
  images: CatalogReviewImage[];
  profile: { id: string; name: string } | null;
  printed: boolean | null;
  issues: string[];
  boosted: boolean;
  reply_preview: CatalogReview[];
}

export interface CatalogReviewsResponse {
  items: CatalogReview[];
  total: number | null;
  has_more: boolean;
  kind: CatalogReviewKind;
  sort: CatalogReviewSort;
  page: number;
  page_size: number;
}

export interface CatalogSavedFile {
  library_file_id: number;
  filename: string;
  folder_id: number | null;
  was_existing: boolean;
}

export interface CatalogBrowseParams {
  query: string;
  sort: CatalogSort;
  category: string;
  offset: number;
  limit: number;
  printerModels: string[];
  printerFilter: boolean;
  authorPrinter: boolean;
}

/** Curtidos / salvos do próprio usuário no MakerWorld. */
export type CatalogMineKind = 'likes' | 'saved';

export interface CatalogAuthorResponse {
  items: CatalogCard[];
  total: number | null;
  has_more: boolean;
  author: { id: string; name: string | null };
}
