import { useTranslation } from 'react-i18next';
import { ScrollableModalOverlay } from '../dialogs/ScrollableModalOverlay';
import { FixedSlicePrinter, useA1Nozzle, type FixedPrinterPresets } from './fixedPrinter';

export function RetryPipelineNozzleDialog({ options, pending, onClose, onRetry }: {
  options: FixedPrinterPresets;
  pending: boolean;
  onClose: () => void;
  onRetry: (diameter: string) => void;
}) {
  const { t } = useTranslation();
  const nozzle = useA1Nozzle(options);
  const title = t('pipelineRuns.retryFailed', 'Retry failed');

  return (
    <ScrollableModalOverlay className="bg-black/60" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-md space-y-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary p-4 shadow-xl">
        <h3 className="font-semibold text-white">{title}</h3>
        <FixedSlicePrinter options={options} value={nozzle.diameter} onChange={nozzle.select} disabled={pending} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={pending} className="min-h-11 rounded px-3 text-sm text-bambu-gray">
            {t('common.cancel')}
          </button>
          <button
            type="button"
            disabled={pending || !nozzle.diameter}
            onClick={() => { if (nozzle.diameter) onRetry(nozzle.diameter); }}
            className="min-h-11 rounded bg-bambu-green px-3 text-sm font-medium text-bambu-dark disabled:opacity-50"
          >
            {title}
          </button>
        </div>
      </div>
    </ScrollableModalOverlay>
  );
}
