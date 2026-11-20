import { Layers } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

/**
 * Modo impressora única: pedaços que saem da linha "0.4mm · 🕒 10h" do cabeçalho do card.
 *  - as horas totais de impressão saíram do card (pedido de 2026-11-19);
 *  - o diâmetro do bico vira um selo verde na linha de selos.
 */
export function NozzleSizeBadge({ diameters, type }: { diameters: Array<number | string>; type?: string | null }) {
  if (diameters.length === 0) return null;
  return (
    <span
      className="flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-status-ok/20 text-status-ok"
      title={type || 'Bico'}
    >
      {diameters.join(' / ')}mm
    </span>
  );
}

/** Itens na fila: no card compacto sai da linha de selos e vai para a linha de controles, ao lado da verificação de placa. */
export function QueueChip({ count }: { count: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  if (!count || count <= 0) return null;
  return (
    <button
      onClick={() => navigate('/queue')}
      className="flex h-8 items-center gap-1 px-2.5 rounded-lg text-xs bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-400 hover:opacity-80 transition-opacity"
      title={t('printers.queue.inQueue', { count })}
      data-testid="custom-queue-chip"
    >
      <Layers className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
      {count}
    </button>
  );
}
