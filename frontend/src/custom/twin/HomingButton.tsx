import { Home } from 'lucide-react';
import { useTwinStrings } from './i18n';

export function HomingButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  const s = useTwinStrings();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="mx-3 mb-2.5 flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-indigo-100 px-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-200 disabled:opacity-50 dark:bg-indigo-500/15 dark:text-indigo-300 dark:hover:bg-indigo-500/30"
    >
      <Home className="h-4 w-4" aria-hidden="true" />
      {s.homing}
    </button>
  );
}
