import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, RotateCcw } from 'lucide-react';
import { withStreamToken } from '../../api/client';
import {
  moveCorner, moveQuad, pointInQuad, quadToRoi, rectToQuad, roiToQuad,
  type Point, type Quad, type QuadRoi,
} from './plateRoiGeom';

/**
 * Editor da área de detecção da mesa: 4 cantos livres arrastados por mouse ou toque sobre a imagem da mesa
 * vazia (referência mais recente; sem referência, a imagem de análise). Arrastar dentro da área move tudo.
 * Toque num canto o seleciona para o ajuste fino pelas setas (0,5% por toque).
 */
interface Props {
  printerId: number;
  value: QuadRoi;
  onChange: (roi: QuadRoi) => void;
  fallbackImage?: string;
  defaultRoi?: QuadRoi;
}

type Drag = { kind: 'corner'; index: number } | { kind: 'move'; last: Point };

const NUDGE = 0.005;
const LABELS = ['1', '2', '3', '4'];

export function PlateRoiEditor({ printerId, value, onChange, fallbackImage, defaultRoi }: Props) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [selected, setSelected] = useState(0);
  const [src, setSrc] = useState(() =>
    withStreamToken(`/api/v1/custom/plate-roi/${printerId}/backdrop.jpg?t=${Date.now()}`));
  const [loaded, setLoaded] = useState(false);
  const quad = roiToQuad(value);

  useEffect(() => setLoaded(false), [src]);

  const toPoint = useCallback((e: { clientX: number; clientY: number }): Point => {
    const r = box.current!.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  }, []);

  const emit = (next: Quad) => onChange(quadToRoi(next));

  const startCorner = (index: number) => (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    box.current?.setPointerCapture(e.pointerId);
    drag.current = { kind: 'corner', index };
    setSelected(index);
  };

  const onBoxDown = (e: ReactPointerEvent) => {
    const p = toPoint(e);
    if (!pointInQuad(quad, p)) return;
    e.preventDefault();
    box.current?.setPointerCapture(e.pointerId);
    drag.current = { kind: 'move', last: p };
  };

  const onMove = (e: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    e.preventDefault();
    const p = toPoint(e);
    if (d.kind === 'corner') {
      emit(moveCorner(quad, d.index, p));
    } else {
      emit(moveQuad(quad, p[0] - d.last[0], p[1] - d.last[1]));
      d.last = p;
    }
  };

  const onUp = (e: ReactPointerEvent) => {
    if (!drag.current) return;
    drag.current = null;
    if (box.current?.hasPointerCapture(e.pointerId)) box.current.releasePointerCapture(e.pointerId);
  };

  const nudge = (dx: number, dy: number) => {
    const [x, y] = quad[selected];
    emit(moveCorner(quad, selected, [x + dx, y + dy]));
  };

  const polygon = quad.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');

  return (
    <div className="space-y-2 bg-bambu-dark-tertiary/50 p-2 rounded-lg" data-testid="plate-roi-editor">
      <div
        ref={box}
        className="relative w-full select-none overflow-visible rounded-md bg-black"
        style={{ touchAction: 'none', aspectRatio: loaded ? undefined : '16 / 9' }}
        onPointerDown={onBoxDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
      >
        <img
          src={src}
          alt={t('customPlateRoi.backdrop')}
          draggable={false}
          className="block w-full rounded-md pointer-events-none"
          onLoad={() => setLoaded(true)}
          onError={() => { if (fallbackImage && src !== fallbackImage) setSrc(fallbackImage); }}
        />
        <svg className="absolute inset-0 h-full w-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points={polygon} fill="rgba(34,197,94,0.22)" stroke="rgb(34,197,94)" strokeWidth="2"
            vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </svg>
        {quad.map(([x, y], i) => (
          <button
            key={i}
            type="button"
            aria-label={t('customPlateRoi.corner', { n: i + 1 })}
            data-corner={i}
            onPointerDown={startCorner(i)}
            onClick={() => setSelected(i)}
            className="absolute flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
            style={{ left: `${x * 100}%`, top: `${y * 100}%`, touchAction: 'none' }}
          >
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full border-2 text-[10px] font-bold shadow ${
                selected === i ? 'border-white bg-green-500 text-white' : 'border-green-500 bg-white/90 text-green-700'
              }`}
            >
              {LABELS[i]}
            </span>
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1" aria-label={t('customPlateRoi.fine')}>
          {([[ArrowLeft, -NUDGE, 0], [ArrowUp, 0, -NUDGE], [ArrowDown, 0, NUDGE], [ArrowRight, NUDGE, 0]] as const).map(
            ([Icon, dx, dy], k) => (
              <button key={k} type="button" onClick={() => nudge(dx, dy)}
                className="flex h-10 w-10 items-center justify-center rounded-md bg-bambu-dark-tertiary text-white active:bg-bambu-dark"
                aria-label={t('customPlateRoi.nudge')}>
                <Icon className="h-4 w-4" />
              </button>
            ),
          )}
          <span className="ml-1 text-xs text-bambu-gray">{LABELS[selected]}</span>
        </div>
        <button type="button" onClick={() => emit(defaultRoi ? roiToQuad(defaultRoi) : rectToQuad({ x: 0.15, y: 0.35, w: 0.7, h: 0.55 }))}
          className="flex h-10 items-center gap-1 rounded-md px-2 text-xs text-bambu-gray hover:text-white">
          <RotateCcw className="h-3.5 w-3.5" />
          {t('customPlateRoi.reset')}
        </button>
      </div>
      <p className="text-xs text-bambu-gray">{t('customPlateRoi.instruction')}</p>
    </div>
  );
}
