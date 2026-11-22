import { useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, Ban, CheckCircle2, Layers, Search, SkipForward, SlidersHorizontal, Square, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { api, type PrintLogEntry } from '../../api/client';
import { Card, CardContent } from '../../components/Card';
import { ColorSubstitutionNotes } from '../../components/ColorSubstitutionNotes';
import { formatDateTime, formatDuration, type TimeFormat } from '../../utils/date';
import { queueItemThumbnailUrl } from '../../utils/queueItemThumbnail';

export const printHistoryDate = (entry: PrintLogEntry) => entry.completed_at || entry.started_at || entry.created_at;
export const printHistoryKey = (entry: PrintLogEntry) => `${entry.queue_only ? 'queue' : 'run'}:${entry.id}`;
export const printHistoryQueueLabel = (entry: PrintLogEntry) => entry.started_at || entry.status === 'completed'
  ? 'customPrintHistory.queueRecord'
  : 'customPrintHistory.beforeStart';

export function historyDateBoundary(value: string, end = false): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T${end ? '23:59:59.999' : '00:00:00.000'}`);
  if (!Number.isFinite(date.getTime())) return undefined;
  return date.toISOString().replace('Z', end ? '999' : '');
}

function statusKey(status: string) {
  return status === 'aborted' ? 'cancelled' : status;
}

export function PrintHistoryStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  const key = statusKey(status);
  return t(`archives.log.statuses.${key}`, { defaultValue: status });
}

export function PrintHistoryName({ entry }: { entry: PrintLogEntry }) {
  const { t } = useTranslation();
  const [failedThumbnail, setFailedThumbnail] = useState<string>();
  const thumbnail = entry.queue_item
    ? queueItemThumbnailUrl({
        ...entry.queue_item,
        archive_thumbnail: entry.archive_available ? entry.queue_item.archive_thumbnail : null,
        library_file_thumbnail: entry.library_file_available ? entry.queue_item.library_file_thumbnail : null,
      })
    : entry.thumbnail_path ? api.getPrintLogThumbnail(entry.id) : null;
  const name = entry.print_name || t('customPrintHistory.untitled', { id: entry.id });
  const archive = entry.archive_available && entry.archive_id != null
    ? `/archives/${entry.archive_id}${entry.queue_only ? '' : `?run=${entry.id}`}`
    : null;
  const archiveThumbnail = archive && entry.archive_has_thumbnail && entry.archive_id != null
    ? api.getArchiveThumbnail(entry.archive_id)
    : null;
  const visibleThumbnail = thumbnail && thumbnail !== failedThumbnail ? thumbnail : archiveThumbnail;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <div className="relative grid size-9 shrink-0 place-items-center overflow-hidden rounded bg-bambu-dark text-bambu-gray">
        <Layers className="size-4" aria-hidden />
        {visibleThumbnail && (
          <img key={visibleThumbnail} src={visibleThumbnail} alt="" loading="lazy" className="absolute inset-0 size-full object-cover"
            onError={(event) => {
              if (visibleThumbnail === thumbnail && archiveThumbnail !== thumbnail) setFailedThumbnail(thumbnail);
              else event.currentTarget.style.display = 'none';
            }} />
        )}
      </div>
      {archive ? (
        <Link to={archive} className="text-sm font-medium text-white break-words min-w-0 hover:text-bambu-green hover:underline" title={name}>
          {name}
        </Link>
      ) : <span className="text-sm font-medium text-white break-words min-w-0">{name}</span>}
    </div>
  );
}

interface HistoryFilterValues {
  search: string;
  status: string;
  username: string;
  printer: string;
  dateFrom: string;
  dateTo: string;
}

export function PrintHistoryFilters({ values, onFilter, printers, users, sort, sortLabels, onSort, onColumns }: {
  values: HistoryFilterValues;
  onFilter: (key: keyof HistoryFilterValues, value: string) => void;
  printers?: { id: number; name: string }[];
  users?: { id: number; username: string }[];
  sort: { column: string; direction: 'asc' | 'desc' };
  sortLabels: Record<string, string>;
  onSort: (column: string) => void;
  onColumns: () => void;
}) {
  const { t } = useTranslation();
  const [showFilters, setShowFilters] = useState(false);
  const moreActive = Boolean(values.username || values.printer || values.dateFrom || values.dateTo);
  const inputClass = 'min-w-0 min-h-10 w-full rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-2.5 py-1 text-sm text-white focus:border-bambu-green focus:outline-none';
  const orderLabel = t('archives.log.sortBy', { column: t(sortLabels[sort.column] ?? sort.column) });
  const sortOptions = new Set(['date', 'print_name', 'status', 'duration', ...(printers ? ['printer'] : []), sort.column]);

  return (
    <Card>
      <CardContent className="py-3">
        <div className="grid grid-cols-[1fr_auto] gap-2 sm:flex sm:items-center">
          <label className="relative col-span-2 sm:flex-1">
            <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-bambu-gray" aria-hidden />
            <input type="search" className={`${inputClass} pl-8`} value={values.search}
              aria-label={t('archives.searchPlaceholder')} placeholder={t('archives.searchPlaceholder')}
              onChange={(event) => onFilter('search', event.target.value)} />
          </label>
          <select className={`${inputClass} sm:w-auto`} aria-label={t('archives.log.allStatuses')} value={values.status}
            onChange={(event) => onFilter('status', event.target.value)}>
            <option value="">{t('archives.log.allStatuses')}</option>
            {['completed', 'failed', 'stopped', 'cancelled', 'skipped'].map((status) => (
              <option key={status} value={status}>{t(`archives.log.statuses.${status}`)}</option>
            ))}
          </select>
          <button type="button" aria-expanded={showFilters} onClick={() => setShowFilters(!showFilters)}
            className={`${inputClass} flex items-center justify-center gap-1.5 sm:w-auto ${moreActive ? 'border-bambu-green' : ''}`}>
            <SlidersHorizontal className="size-4" aria-hidden />
            {t('customPrintHistory.filters')}
          </button>
          <button type="button" onClick={onColumns} className={`${inputClass} hidden md:block md:w-auto`}>
            {t('archives.log.columns')}
          </button>
          <div className="col-span-2 flex gap-2 md:hidden">
            <select className={inputClass} aria-label={t('customPrintHistory.sort')} value={sort.column}
              onChange={(event) => onSort(event.target.value)}>
              {[...sortOptions].map((column) => (
                <option key={column} value={column}>{t('archives.log.sortBy', { column: t(sortLabels[column] ?? column) })}</option>
              ))}
            </select>
            <button type="button" className={`${inputClass} !w-11 shrink-0`} onClick={() => onSort(sort.column)}
              aria-label={t(sort.direction === 'asc' ? 'customPrintHistory.descending' : 'customPrintHistory.ascending')}
              title={orderLabel}>
              {sort.direction === 'asc' ? <ArrowUp className="size-4 mx-auto" /> : <ArrowDown className="size-4 mx-auto" />}
            </button>
          </div>
        </div>
        {showFilters && (
          <div className="mt-3 grid grid-cols-2 gap-2 md:flex md:items-end md:flex-wrap">
            <label className="min-w-0 text-xs text-bambu-gray">
              {t('archives.log.dateFrom')}
              <input type="date" className={inputClass} value={values.dateFrom} onChange={(event) => onFilter('dateFrom', event.target.value)} />
            </label>
            <label className="min-w-0 text-xs text-bambu-gray">
              {t('archives.log.dateTo')}
              <input type="date" className={inputClass} value={values.dateTo} onChange={(event) => onFilter('dateTo', event.target.value)} />
            </label>
            {printers && (
              <select className={`${inputClass} md:w-auto`} aria-label={t('archives.log.allPrinters')} value={values.printer}
                onChange={(event) => onFilter('printer', event.target.value)}>
                <option value="">{t('archives.log.allPrinters')}</option>
                {printers.map((printer) => <option value={printer.id} key={printer.id}>{printer.name}</option>)}
              </select>
            )}
            {users && (
              <select className={`${inputClass} md:w-auto`} aria-label={t('archives.log.allUsers')} value={values.username}
                onChange={(event) => onFilter('username', event.target.value)}>
                <option value="">{t('archives.log.allUsers')}</option>
                {users.map((user) => <option value={user.username} key={user.id}>{user.username}</option>)}
              </select>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const STATUS_STYLES = {
  completed: { icon: CheckCircle2, className: 'border-l-emerald-500 text-emerald-600 dark:text-emerald-400' },
  failed: { icon: XCircle, className: 'border-l-red-500 text-red-600 dark:text-red-400' },
  stopped: { icon: Square, className: 'border-l-amber-500 text-amber-600 dark:text-amber-400' },
  skipped: { icon: SkipForward, className: 'border-l-amber-500 text-amber-600 dark:text-amber-400' },
  cancelled: { icon: Ban, className: 'border-l-gray-500 text-bambu-gray' },
};

export function PrintHistoryCards({ entries, timeFormat, single, renderActions }: {
  entries: PrintLogEntry[];
  timeFormat: TimeFormat;
  single: boolean;
  renderActions: (entry: PrintLogEntry) => ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <ul className="space-y-2 p-2 md:hidden">
      {entries.map((entry) => {
        const key = statusKey(entry.status);
        const status = STATUS_STYLES[key as keyof typeof STATUS_STYLES] ?? STATUS_STYLES.cancelled;
        const failure = entry.queue_item?.error_message || (entry.failure_reason
          ? t(`editArchive.failureReasons.${entry.failure_reason}`, { defaultValue: entry.failure_reason }) : null);
        return (
          <li key={printHistoryKey(entry)} className={`border-l-[3px] bg-bambu-dark-secondary rounded-md p-2.5 ${status.className}`}>
            <div className="flex min-w-0 items-start justify-between gap-1.5">
              <PrintHistoryName entry={entry} />
              {renderActions(entry)}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs">
              <span className="inline-flex gap-1 items-center font-medium"><status.icon className="size-3.5" aria-hidden />
                <PrintHistoryStatus status={entry.status} />
              </span>
              <time className="text-bambu-gray" dateTime={printHistoryDate(entry)}>{formatDateTime(printHistoryDate(entry), timeFormat)}</time>
              {entry.queue_only && <span className="text-bambu-gray">{t(printHistoryQueueLabel(entry))}</span>}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-2.5 gap-y-1 text-xs text-bambu-gray">
              {!single && entry.printer_name && <span>{entry.printer_name}</span>}
              {entry.duration_seconds != null && <span>{formatDuration(entry.duration_seconds)}</span>}
              {entry.filament_used_grams != null && <span>{Math.round(entry.filament_used_grams)} g {entry.filament_type}</span>}
              {entry.created_by_username && <span>{entry.created_by_username}</span>}
            </div>
            {failure && <p className="mt-1 break-words text-xs text-bambu-gray-light">{failure}</p>}
            {entry.queue_item && <ColorSubstitutionNotes substitutions={entry.queue_item.color_substitutions} t={t} className="mt-1 text-xs" />}
          </li>
        );
      })}
    </ul>
  );
}
