import { CalendarDays, FolderOpen, History } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

type ArchiveView = 'grid' | 'list' | 'log' | 'calendar';

export function useUnifiedPrintHistory(): boolean {
  const { hasAnyPermission } = useAuth();
  const preference = localStorage.getItem('custom.printHistory');
  if (preference === 'off' || (preference !== 'on' && import.meta.env.MODE === 'test')) return false;
  return hasAnyPermission('archives:read_all', 'archives:read_own');
}

export function QueueHistoryRedirect({ children }: { children: ReactNode }) {
  const enabled = useUnifiedPrintHistory();
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (enabled && !params.has('batch') && params.get('tab') === 'history') {
    return <Navigate replace to="/archives?view=history" />;
  }
  return children;
}

export function initialPrintHistoryView(enabled: boolean): ArchiveView {
  const saved = localStorage.getItem('archiveViewMode') as ArchiveView | null;
  if (!enabled) return saved || 'grid';
  if (new URLSearchParams(window.location.search).has('highlight')) return savedFilesView();
  return 'log';
}

export function savedFilesView(): 'grid' | 'list' {
  return localStorage.getItem('archiveViewMode') === 'list' ? 'list' : 'grid';
}

export function PrintHistoryViews({ view, onChange }: { view: ArchiveView; onChange: (view: ArchiveView) => void }) {
  const { t } = useTranslation();
  const files = view === 'grid' || view === 'list';
  const tabs = [
    { id: 'log', label: t('customPrintHistory.history'), icon: History, active: view === 'log' },
    { id: savedFilesView(), label: t('customPrintHistory.files'), icon: FolderOpen, active: files },
    { id: 'calendar', label: t('customPrintHistory.calendar'), icon: CalendarDays, active: view === 'calendar' },
  ] as const;
  return (
    <div className="flex gap-1 border-b border-bambu-dark-tertiary my-4" role="group" aria-label={t('archives.page.title')}>
      {tabs.map(({ id, icon: Icon, label, active }) => (
        <button
          type="button"
          key={id}
          aria-pressed={active}
          onClick={() => { if (!active) onChange(id); }}
          className={`flex items-center gap-1.5 min-h-11 px-2 sm:px-4 border-b-2 text-sm transition-colors ${
            active ? 'border-bambu-green text-white font-medium' : 'border-transparent text-bambu-gray hover:text-white'
          }`}
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {label}
        </button>
      ))}
    </div>
  );
}
