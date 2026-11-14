import { useTwinAvailable, useTwinViewMode, type TwinViewMode } from './useTwinView';
import { useTwinStrings } from './i18n';

export interface TwinSwitchProps {
  printerId: number;
  /** 'md' (padrão): alvo de toque de 36 px, para celular/PWA; 'sm': cabeçalhos compactos no desktop. */
  size?: 'sm' | 'md';
  className?: string;
}

const MODES: TwinViewMode[] = ['camera', 'twin'];

/**
 * Chave segmentada "Câmera | 3D". Só aparece quando o twin está disponível para a impressora (A1 + interruptor).
 * Dois botões com `aria-pressed` (Tab/Enter/Espaço; setas alternam), sem depender de hover.
 */
export function TwinSwitch({ printerId, size = 'md', className = '' }: TwinSwitchProps) {
  const available = useTwinAvailable(printerId);
  const [mode, setMode] = useTwinViewMode();
  const s = useTwinStrings();
  if (!available) return null;

  const pad = size === 'sm' ? 'min-h-[28px] min-w-[40px] px-2 text-xs' : 'min-h-[36px] min-w-[48px] px-3 text-sm';
  return (
    <div
      role="group"
      aria-label={s.group}
      data-testid="twin-switch"
      className={`no-drag inline-flex items-center rounded-md border border-white/10 bg-black/40 p-0.5 ${className}`}
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          e.preventDefault();
          setMode(mode === 'camera' ? 'twin' : 'camera');
        }
      }}
    >
      {MODES.map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          onClick={() => setMode(m)}
          className={`${pad} rounded font-medium leading-none transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-bambu-green ${
            mode === m ? 'bg-bambu-green text-white' : 'text-bambu-gray hover:text-white'
          }`}
        >
          {m === 'camera' ? s.camera : s.twin}
        </button>
      ))}
    </div>
  );
}
