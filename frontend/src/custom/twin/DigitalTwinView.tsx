import { useEffect, useRef, useState } from 'react';
import { withStreamToken } from '../../api/client';
import { createTwin, type TwinHandle, type MotionStatus } from './engine/engine.js';
import { useTwinStrings } from './i18n';
import { VisualCheck } from './VisualCheck';

const BASE = '/api/v1/custom/twin/stream';
const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

export interface DigitalTwinViewProps {
  printerId: number;
  className?: string;
}

/**
 * Gêmeo digital 3D da A1: só o canvas (nenhum controle visível). Arrastar gira, pinça/roda dá zoom.
 * Estado e G-code vêm do backend do fork (`/api/v1/custom/twin/...`) com o mesmo token de stream da câmera.
 * Ajustes opcionais pela URL da página: `?twinDebug` (expõe window.__twin), `?twinModel=procedural`, `?twinLead=0.8`.
 */
export default function DigitalTwinView({ printerId, className = '' }: DigitalTwinViewProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const twin = useRef<TwinHandle | null>(null);
  const [failed, setFailed] = useState(false);
  const [motionStatus, setMotionStatus] = useState<MotionStatus>('unknown');
  const s = useTwinStrings();
  const positionLabel = motionStatus === 'estimated' ? s.manualEstimate : motionStatus === 'unknown' ? s.unknownPosition : null;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const q = new URLSearchParams(window.location.search);
    let handle: TwinHandle | null = null;
    try {
      handle = createTwin(el, {
        printerId,
        onMotionStatus: setMotionStatus,
        eventsUrl: () => withStreamToken(`${BASE}/${printerId}/events`),
        jobUrl: (id) => withStreamToken(`${BASE}/${printerId}/job/${encodeURIComponent(id)}`),
        modelUrl: () => withStreamToken(`${BASE}/${printerId}/model.glb`),
        debug: q.has('twinDebug'),
        procedural: q.get('twinModel') === 'procedural',
        tuning: { lead: Number(q.get('twinLead')) || 0 },
      });
      twin.current = handle;
      setFailed(false);
    } catch (e) {
      // sem WebGL (navegador/GPU): avisa no próprio quadro, sem derrubar a tela da câmera
      console.warn('twin indisponível', e);
      setFailed(true);
    }
    return () => { twin.current = null; handle?.dispose(); };
  }, [printerId]);

  return (
    <div
      ref={ref}
      role="group"
      aria-label={positionLabel && !failed ? `${s.twinLabel}. ${positionLabel}` : s.twinLabel}
      data-testid="digital-twin-view"
      // gestos são do canvas (girar/zoom do twin): não chegam ao pan/zoom da imagem da câmera no quadro em volta
      onWheel={stop}
      onMouseDown={stop}
      onMouseMove={stop}
      onMouseUp={stop}
      onTouchStart={stop}
      onTouchMove={stop}
      onTouchEnd={stop}
      className={`absolute inset-0 overflow-hidden bg-[#171a21] select-none ${className}`}
    >
      {!failed && <VisualCheck key={printerId} printerId={printerId} twin={twin} />}
      {!failed && positionLabel && (
        <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs text-white">
          {positionLabel}
        </span>
      )}
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-bambu-gray p-4 text-center">
          {s.unavailable}
        </div>
      )}
    </div>
  );
}
