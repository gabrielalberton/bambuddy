import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowLeft, Box, Check, ExternalLink, Loader2, Save, Scissors } from 'lucide-react';
import { api, type LibraryFolderTree } from '../../api/client';
import { SliceModal } from '../../components/SliceModal';
import { ModelViewerModal } from '../../components/ModelViewerModal';
import { GlbPreviewModal } from './GlbPreviewModal';
import { useAuth } from '../../contexts/AuthContext';
import { catalogApi } from './api';
import { useCatalogT, type CatalogKey } from './i18n';
import { controlClass, sourceName } from './constants';
import { CatalogError, CatalogImage } from './shared';
import { ModelStatsRow, ProfileDetails } from './ModelInfo';
import { RatingSummary, ReviewsSection } from './Reviews';
import type { CatalogFile, CatalogSavedFile, CatalogSourceId, PrinterMatch } from './types';
import type { PrinterModels } from './usePrinterModels';
import { safeExternalUrl, sanitizeDescription } from './utils';

function writableFolders(folders: LibraryFolderTree[], parent = ''): { id: number; name: string }[] {
  return folders.flatMap((folder) => {
    const name = parent ? `${parent} / ${folder.name}` : folder.name;
    return [
      ...(folder.can_write && !folder.external_readonly ? [{ id: folder.id, name }] : []),
      ...writableFolders(folder.children ?? [], name),
    ];
  });
}

const MATCH_KEY: Record<PrinterMatch, CatalogKey> = {
  native: 'matchNative',
  compatible: 'matchCompatible',
  unknown: 'matchUnknown',
  other: 'matchOther',
};
const MATCH_CLASS: Record<PrinterMatch, string> = {
  native: 'bg-bambu-green/20 text-bambu-green',
  compatible: 'bg-bambu-green/10 text-bambu-green',
  unknown: 'bg-bambu-dark-tertiary text-bambu-gray',
  other: 'bg-yellow-500/10 text-yellow-400',
};

export function ModelDetail({ source, id, printer, onBack, onOpenModel, onOpenAuthor }: {
  source: CatalogSourceId;
  id: string;
  printer: PrinterModels;
  onBack: () => void;
  /** link para outro modelo (ex.: na descrição) aberto dentro do catálogo */
  onOpenModel?: (source: CatalogSourceId, id: string) => void;
  /** catálogo do autor dentro do Bambuddy */
  onOpenAuthor?: (source: CatalogSourceId, authorId: string, name: string) => void;
}) {
  const t = useCatalogT();
  const { hasPermission } = useAuth();
  const client = useQueryClient();
  const canSave = source === 'makerworld' ? hasPermission('makerworld:import') : hasPermission('library:upload');
  const detail = useQuery({
    queryKey: ['custom-models', source, 'detail', id, printer.models],
    queryFn: ({ signal }) => catalogApi.detail(source, id, printer.models, signal),
    staleTime: 60_000,
    retry: false,
  });
  const folders = useQuery({ queryKey: ['library-folders'], queryFn: api.getLibraryFolders, enabled: canSave, retry: false });
  const [picked, setPicked] = useState<string | null>(null);
  const [folderId, setFolderId] = useState<number | null>(null);
  const [busy, setBusy] = useState<'save' | 'slice' | 'view3d' | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<CatalogSavedFile | null>(null);
  const [sliceFile, setSliceFile] = useState<CatalogSavedFile | null>(null);
  const [viewFile, setViewFile] = useState<CatalogSavedFile | null>(null);
  const [glbOpen, setGlbOpen] = useState(false);
  const [imageIndex, setImageIndex] = useState(0);
  const [reviewsRequested, setReviewsRequested] = useState(false);
  const openReviews = () => {
    setReviewsRequested(true);
    document.getElementById('catalog-reviews')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };
  const mounted = useRef(true);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    heading.current?.focus();
    window.scrollTo?.({ top: 0 });
  }, [detail.data?.id]);

  const data = detail.data;
  const selectedId = picked ?? data?.preselect_file_id ?? null;
  const file = data?.files.find((f) => f.id === selectedId);
  const html = useMemo(() => sanitizeDescription(data?.description_html ?? ''), [data?.description_html]);
  const images = Array.from(new Set([...(data?.images ?? []), ...(data?.thumbnail ? [data.thumbnail] : [])]));
  const folderList = writableFolders(folders.data ?? []);

  const run = async (action: 'save' | 'slice' | 'view3d') => {
    if (!file || busy) return;
    setBusy(action);
    setError(null);
    setSaved(null);
    try {
      const result = await catalogApi.save(source, id, file.id, folderId);
      if (!mounted.current) return;
      for (const key of ['library-files', 'library-folders', 'library-stats']) void client.invalidateQueries({ queryKey: [key] });
      if (action === 'slice') setSliceFile(result);
      else if (action === 'view3d') setViewFile(result);
      else setSaved(result);
    } catch (e) {
      if (mounted.current) setError(e);
    } finally {
      if (mounted.current) setBusy(null);
    }
  };

  return (
    <div className="space-y-4 pb-2">
      <div className="flex items-center justify-between gap-3">
        <button type="button" className={controlClass} onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t('back')}
        </button>
        {data && (
          <div className="flex min-w-0 items-center gap-3 text-sm">
            <span className="truncate text-bambu-green">{sourceName[source]}</span>
            {safeExternalUrl(data.url) && (
              <a
                className="inline-flex min-h-11 shrink-0 items-center gap-1 text-bambu-green underline underline-offset-4 md:min-h-0"
                href={safeExternalUrl(data.url)}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t('original')}
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            )}
          </div>
        )}
      </div>
      {detail.isPending ? (
        <div role="status" className="flex min-h-48 items-center justify-center gap-2 rounded-xl bg-bambu-dark-secondary text-bambu-gray">
          <Loader2 className="h-5 w-5 motion-safe:animate-spin" aria-hidden="true" />
          {t('loading')}
        </div>
      ) : detail.isError ? (
        <CatalogError error={detail.error} onRetry={() => void detail.refetch()} />
      ) : data ? (
        <>
          <header>
            <h2 ref={heading} tabIndex={-1} className="break-words text-xl font-bold text-white focus:outline-none md:text-3xl">
              {data.title}
            </h2>
            {data.rating && (
              <div className="mt-1">
                <RatingSummary rating={data.rating} onClick={data.reviews ? openReviews : undefined} />
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-bambu-gray">
              {data.creator_id && onOpenAuthor ? (
                <button
                  type="button"
                  className="text-left text-bambu-green underline underline-offset-4"
                  onClick={() => onOpenAuthor(source, data.creator_id as string, data.creator)}
                >
                  {t('by', { creator: data.creator })}
                </button>
              ) : (
                <span>{t('by', { creator: data.creator })}</span>
              )}
            </div>
            <ModelStatsRow stats={data.stats} />
          </header>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-2">
              <div className="-mx-4 aspect-[4/3] overflow-hidden bg-bambu-dark-secondary md:mx-0 md:rounded-xl">
                <CatalogImage source={source} url={images[imageIndex] ?? null} alt={data.title} className="h-full w-full object-contain" />
              </div>
              {images.length > 1 && (
                <div className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0" role="group" aria-label={t('gallery')}>
                  {images.map((url, index) => (
                    <button
                      key={url}
                      type="button"
                      onClick={() => setImageIndex(index)}
                      aria-pressed={index === imageIndex}
                      className={`h-16 w-20 shrink-0 snap-start overflow-hidden rounded-lg border-2 ${index === imageIndex ? 'border-bambu-green' : 'border-transparent'}`}
                    >
                      <CatalogImage source={source} url={url} alt="" className="h-full w-full object-cover" />
                    </button>
                  ))}
                </div>
              )}
            </div>

            <section aria-labelledby="catalog-files" className="min-w-0 space-y-3 rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-3 md:p-4">
              <div>
                <h3 id="catalog-files" className="text-base font-semibold text-white">{t('files')}</h3>
                <p className="mt-0.5 text-xs text-bambu-gray">{t('filesHint')}</p>
              </div>
              {data.files.length === 0 ? (
                <p className="text-sm text-bambu-gray">{t('noFiles')}</p>
              ) : (
                <fieldset disabled={busy !== null} className="max-h-[50vh] space-y-2 overflow-y-auto md:max-h-96">
                  <legend className="sr-only">{t('files')}</legend>
                  {data.files.map((f) => (
                    <FileRow key={f.id} file={f} checked={f.id === selectedId} printerLabel={printer.label} onPick={() => { setPicked(f.id); setSaved(null); setError(null); }} />
                  ))}
                </fieldset>
              )}
              {file?.printer_match === 'other' && <p role="status" className="text-sm text-yellow-400">{t('wrongProfileWarning', { printer: printer.label })}</p>}
              {!canSave ? (
                <p className="text-sm text-bambu-gray">{t('noImportPermission')}</p>
              ) : (
                <label className="block text-sm text-bambu-gray">
                  {t('destination')}
                  <select
                    value={folderId ?? ''}
                    onChange={(e) => setFolderId(e.target.value === '' ? null : Number(e.target.value))}
                    disabled={busy !== null || folders.isPending}
                    className={`${controlClass} mt-1 w-full bg-bambu-dark`}
                  >
                    <option value="">{t('defaultFolder', { folder: sourceName[source] })}</option>
                    {folderList.map((f) => (
                      <option key={f.id} value={f.id}>{f.name}</option>
                    ))}
                  </select>
                </label>
              )}
              {source === 'makerworld' && canSave && <p className="text-xs text-bambu-gray">{t('makerworldSignIn')}</p>}
              {saved && (
                <div role="status" className="rounded-lg bg-bambu-green/10 p-3 text-sm text-bambu-green">
                  <p className="flex items-center gap-2"><Check className="h-4 w-4" aria-hidden="true" />{t(saved.was_existing ? 'alreadySaved' : 'saved', { filename: saved.filename })}</p>
                  <Link to={`/files?highlight=${saved.library_file_id}`} className="mt-2 inline-flex min-h-11 items-center underline underline-offset-4">{t('openLibrary')}</Link>
                </div>
              )}
              {error != null && <CatalogError error={error} compact />}
            </section>
          </div>

          {/* Celular: a barra Salvar/Fatiar fica fixa no rodapé (o <main> do
              Layout não é o elemento que rola, então sticky não funciona). */}
          {canSave && data.files.length > 0 && (
            <div
              className="fixed inset-x-0 bottom-0 z-30 border-t border-bambu-dark-tertiary bg-bambu-dark/95 px-4 pt-3 backdrop-blur md:static md:rounded-xl md:border"
              style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}
            >
              <div className="grid grid-cols-[1fr_1fr_auto] gap-2 md:flex md:flex-wrap">
                <button type="button" className={`${controlClass} !border-bambu-green !bg-bambu-green font-semibold !text-bambu-dark`} disabled={!file || busy !== null} onClick={() => void run('save')}>
                  {busy === 'save' ? <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
                  {t(busy === 'save' ? 'saving' : 'save')}
                </button>
                <button type="button" className={controlClass} disabled={!file?.sliceable || busy !== null} onClick={() => void run('slice')}>
                  {busy === 'slice' ? <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" /> : <Scissors className="h-4 w-4" aria-hidden="true" />}
                  {t(busy === 'slice' ? 'preparing' : 'slice')}
                </button>
                <button type="button" className={controlClass} disabled={!file || busy !== null} onClick={() => (file?.metadata?.preview_3d ? setGlbOpen(true) : void run('view3d'))} aria-label={t(file?.metadata?.preview_3d ? 'preview3d' : 'view3d')} title={t(file?.metadata?.preview_3d ? 'preview3d' : 'view3d')}>
                  {busy === 'view3d' ? <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" /> : <Box className="h-4 w-4" aria-hidden="true" />}
                  3D
                </button>
              </div>
              <p className="mt-2 text-xs text-bambu-gray">{t('sliceHint')}</p>
            </div>
          )}

          <section className="space-y-2 rounded-xl border border-bambu-dark-tertiary p-3 md:p-5">
            <h3 className="text-base font-semibold text-white">{t('description')}</h3>
            {html ? (
              <div
                className="overflow-x-auto break-words text-sm leading-relaxed text-bambu-gray [&_a]:text-bambu-green [&_a]:underline [&_h2]:text-lg [&_h2]:text-white [&_h3]:text-white [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-3 [&_pre]:whitespace-pre-wrap [&_ul]:list-disc [&_ul]:pl-5"
                dangerouslySetInnerHTML={{ __html: html }}
                onClick={(e) => {
                  // link para outro modelo do MakerWorld: abre aqui dentro (o href externo fica como alternativa)
                  const a = (e.target as HTMLElement).closest('a[data-internal-model]');
                  const target = a?.getAttribute('data-internal-model');
                  if (target && onOpenModel) {
                    e.preventDefault();
                    onOpenModel('makerworld', target);
                  }
                }}
              />
            ) : (
              <p className="text-sm text-bambu-gray">{t('noDescription')}</p>
            )}
          </section>

          {data.reviews && data.reviews.kinds.length > 0 && (
            <ReviewsSection source={source} modelId={id} capabilities={data.reviews} rating={data.rating} forceLoad={reviewsRequested} />
          )}
        </>
      ) : null}
      {canSave && (data?.files.length ?? 0) > 0 && <div className="h-36 md:hidden" aria-hidden="true" />}
      {glbOpen && file && (
        <GlbPreviewModal source={source} modelId={id} fileId={file.id} title={`${data?.title ?? ''} · ${file.name}`} onClose={() => setGlbOpen(false)} />
      )}
      {viewFile && (
        <ModelViewerModal libraryFileId={viewFile.library_file_id} title={data?.title ?? viewFile.filename} fileType="3mf" onClose={() => setViewFile(null)} />
      )}
      {sliceFile && (
        <SliceModal source={{ kind: 'libraryFile', id: sliceFile.library_file_id, filename: sliceFile.filename }} onClose={() => setSliceFile(null)} />
      )}
    </div>
  );
}

function FileRow({ file, checked, printerLabel, onPick }: { file: CatalogFile; checked: boolean; printerLabel: string; onPick: () => void }) {
  const t = useCatalogT();
  const plates = Array.isArray(file.metadata.plates) ? file.metadata.plates.length : 0;
  const size = file.size ? `${(file.size / 1048576).toFixed(1)} MB` : null;
  const matchPrinter = file.printer_match === 'native' && file.printer ? file.printer : printerLabel;
  return (
    <label className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border p-3 ${checked ? 'border-bambu-green bg-bambu-green/5' : 'border-bambu-dark-tertiary'}`}>
      <input type="radio" name="catalog-file" checked={checked} onChange={onPick} className="mt-0.5 h-5 w-5 shrink-0 accent-bambu-green" />
      <span className="min-w-0 flex-1">
        <span className="block break-words text-sm font-medium text-white">{file.name}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-bambu-gray">
          <span className={`rounded px-1.5 py-0.5 ${MATCH_CLASS[file.printer_match]}`}>{t(MATCH_KEY[file.printer_match], { printer: matchPrinter })}</span>
          {file.printer && file.printer_match !== 'native' && <span>{file.printer}</span>}
          <span>{file.format.toUpperCase()}</span>
          {size && <span>{size}</span>}
          {plates > 0 && file.metadata.plate_count == null && <span>{t('plates', { count: plates })}</span>}
          {file.metadata.requires_ams === true && <span>{t('ams')}</span>}
          {!file.sliceable && <span>{t('saveOnly')}</span>}
        </span>
        <ProfileDetails file={file} />
      </span>
    </label>
  );
}
