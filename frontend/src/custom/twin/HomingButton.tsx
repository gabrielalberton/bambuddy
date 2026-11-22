import { Home } from 'lucide-react';
import { useTwinStrings } from './i18n';

export function HomingButton({ onClick, onInvalidate, disabled }: {
  onClick: () => void;
  onInvalidate: () => void;
  disabled: boolean;
}) {
  const s = useTwinStrings();
  return (
    <div className="mx-3 mb-2.5 flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="flex min-h-[44px] flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-indigo-100 px-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-200 disabled:opacity-50 dark:bg-indigo-500/15 dark:text-indigo-300 dark:hover:bg-indigo-500/30"
      >
        <Home className="h-4 w-4" aria-hidden="true" />
        {s.homing}
      </button>
      <button
        type="button"
        onClick={onInvalidate}
        className="min-h-[44px] flex-1 whitespace-nowrap rounded-lg bg-bambu-dark px-2 text-xs font-medium text-bambu-gray hover:text-white"
      >
        {s.movedByHand}
      </button>
    </div>
  );
}
