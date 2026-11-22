import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api, type PrintLogEntry } from '../../api/client';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PrintModal } from '../../components/PrintModal';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';

export function useHistoryActions() {
  const { t } = useTranslation();
  const { hasPermission, canModify } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [retry, setRetry] = useState<{
    archiveId?: number;
    libraryFileId?: number;
    name: string;
    plate?: number | null;
  } | null>(null);
  const [removeId, setRemoveId] = useState<number | null>(null);
  const remove = useMutation({
    mutationFn: api.removeFromQueue,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['print-log'] });
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['batches'] });
      showToast(t(result.deleted === false ? 'queue.toast.keptForOrder' : 'queue.toast.removed'));
    },
    onError: () => showToast(t('queue.toast.removeFailed'), 'error'),
  });
  const buttonClass = 'inline-grid size-10 place-items-center rounded-lg text-bambu-gray hover:bg-bambu-dark-tertiary hover:text-white disabled:opacity-40';

  function renderActions(entry: PrintLogEntry, edit: () => void, deleteRun: () => void, busy: boolean) {
    const item = entry.queue_item;
    if (item) {
      const archiveId = entry.archive_available ? item.archive_id ?? undefined : undefined;
      const libraryFileId = entry.library_file_available ? item.library_file_id ?? undefined : undefined;
      return (
        <div className="inline-flex shrink-0 items-center">
          {(archiveId != null || libraryFileId != null) && hasPermission('queue:create') && (
            <button type="button" className={buttonClass} aria-label={t('queue.actions.requeue')} title={t('queue.actions.requeue')}
              onClick={() => setRetry({ archiveId, libraryFileId: archiveId == null ? libraryFileId : undefined,
                name: entry.print_name || t('customPrintHistory.untitled', { id: entry.id }), plate: item.plate_id })}>
              <RefreshCw className="size-4" aria-hidden />
            </button>
          )}
          {canModify('queue', 'delete', item.created_by_id) && (
            <button type="button" className={buttonClass} aria-label={t('common.remove')} title={t('common.remove')}
              onClick={() => setRemoveId(item.id)} disabled={remove.isPending}>
              <Trash2 className="size-4" aria-hidden />
            </button>
          )}
        </div>
      );
    }

    return (
      <div className="inline-flex shrink-0 items-center">
        {canModify('archives', 'update', entry.created_by_id) && (
          <button type="button" className={buttonClass} aria-label={t('archives.log.editEntryTitle')}
            title={t('archives.log.editEntryTitle')} onClick={edit} disabled={busy}>
            <Pencil className="size-4" aria-hidden />
          </button>
        )}
        {canModify('archives', 'delete', entry.created_by_id) && (
          <button type="button" className={buttonClass} aria-label={t('archives.log.deleteEntryTitle')}
            title={t('archives.log.deleteEntryTitle')} onClick={deleteRun} disabled={busy}>
            <Trash2 className="size-4" aria-hidden />
          </button>
        )}
      </div>
    );
  }

  const dialogs = (
    <>
      {retry && (
        <PrintModal mode="create" archiveId={retry.archiveId} libraryFileId={retry.libraryFileId}
          archiveName={retry.name} preselectPlateId={retry.plate} onClose={() => setRetry(null)} />
      )}
      {removeId != null && (
        <ConfirmModal title={t('queue.confirm.removeTitle')} message={t('customPrintHistory.removeQueueConfirm')}
          confirmText={t('common.remove')} variant="danger" onCancel={() => setRemoveId(null)}
          onConfirm={() => { remove.mutate(removeId); setRemoveId(null); }} />
      )}
    </>
  );
  return { renderActions, dialogs };
}
