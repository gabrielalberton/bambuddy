/** Barra de temperatura (componente); escala/cor/opacidade em ./tempBarScale.ts. */
import { isTempBarsEnabled } from '../flags';
import { TEMP_BAR_SCALE, tempBarColor, tempBarOpacity, tempFraction, type TempBarKind } from './tempBarScale';
import './tempBars.css';

interface Temps {
  nozzle?: number;
  nozzle_target?: number;
  nozzle_2?: number;
  bed?: number;
  bed_target?: number;
}

/**
 * Atributo do bloco de temperatura do upstream: com ele, o bloco vira uma linha horizontal de largura inteira
 * (ícone · rótulo · número · barra), como as barras de filamento (layout em ./tempBars.css).
 * Bico duplo fica com os blocos do upstream (os dois, para não misturar linha e bloco).
 */
export function tempRowAttr(kind: TempBarKind, temps: Temps | null | undefined): { 'data-temp-row'?: TempBarKind } {
  if (!temps || !isTempBarsEnabled() || temps.nozzle_2 !== undefined) return {};
  return { 'data-temp-row': kind };
}

/** Gancho no cartão de temperatura do PrinterCard: `<TempBar kind="bed" temps={status.temperatures} />`. */
export function TempBar({ kind, temps }: { kind: TempBarKind; temps: Temps | null | undefined }) {
  if (!temps || !isTempBarsEnabled()) return null;
  if (kind === 'nozzle' && temps.nozzle_2 !== undefined) return null;
  const temp = kind === 'bed' ? temps.bed : temps.nozzle;
  const target = kind === 'bed' ? temps.bed_target : temps.nozzle_target;
  const frac = tempFraction(kind, temp);
  const pct = Math.round(frac * 1000) / 10;
  const showTarget = typeof target === 'number' && target > 0;
  return (
    <div
      data-testid={`temp-bar-${kind}`}
      className="relative mt-1 h-1.5 w-full self-stretch bg-black/30 rounded-full overflow-hidden"
      role="meter"
      aria-valuemin={TEMP_BAR_SCALE[kind].min}
      aria-valuemax={TEMP_BAR_SCALE[kind].max}
      aria-valuenow={typeof temp === 'number' ? Math.round(temp) : undefined}
    >
      <div
        data-testid={`temp-bar-${kind}-fill`}
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, backgroundColor: tempBarColor(frac), opacity: tempBarOpacity(kind, temp) }}
      />
      {showTarget && (
        <div
          data-testid={`temp-bar-${kind}-target`}
          className="absolute top-0 h-full w-0.5 -ml-px bg-white/80"
          style={{ left: `${Math.round(tempFraction(kind, target) * 1000) / 10}%` }}
        />
      )}
    </div>
  );
}
