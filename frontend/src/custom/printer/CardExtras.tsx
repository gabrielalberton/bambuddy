import { Clock } from 'lucide-react';

/**
 * Modo impressora única: pedaços que saem da linha "0.4mm · 🕒 10h" do cabeçalho do card.
 *  - horas totais de impressão viram um tile ao lado de Bico/Cama (mesmo estilo dos tiles do upstream);
 *  - o diâmetro do bico vira um selo verde na linha de selos.
 */
export function PrintHoursTile({ hours }: { hours: number | null | undefined }) {
  if (!hours || hours <= 0) return null;
  return (
    <div className="relative text-center px-2 py-1.5 bg-bambu-dark rounded-lg flex-1 flex flex-col justify-center items-center" title="Tempo total de impressão">
      <Clock className="w-[var(--pc-i35,0.875rem)] h-[var(--pc-i35,0.875rem)] mb-0.5 text-bambu-gray" />
      <p className="text-[length:var(--pc-t9,9px)] text-bambu-gray">Impressão</p>
      <p className="text-[length:var(--pc-t11,11px)] text-white">{Math.round(hours)}h</p>
    </div>
  );
}

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
