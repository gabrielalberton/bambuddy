import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { withStreamToken } from '../../api/client';
import { cameraPreviewEnabled } from './previewFlags';
import { STREAM_IMG_SELECTOR, isWaitingForH264 } from './h264';
import { displayedAspect, fitRect, rememberCameraAspect, rotationFromTransform } from './cameraAspect';

/** Intervalo entre imagens da prévia (o Frigate atualiza a ~3 fps). */
const PREVIEW_INTERVAL_MS = 300;
/** Com que frequência procuramos o <img> do stream do upstream e se ele já tem quadro. */
const WATCH_INTERVAL_MS = 120;
const FADE_MS = 250;
const MAX_FAILURES = 3;

/** Tamanho mínimo para considerar um ancestral como "o quadro" (antes do 1º quadro o contêiner do <img> pode ter 0 px). */
const MIN_FRAME_PX = 120;

type Box = { top: number; left: number; width: number; height: number };

/** Retângulo do primeiro ancestral com tamanho real, em coordenadas do contêiner do <img> (onde a prévia é desenhada). */
function frameBox(img: HTMLImageElement): Box | null {
  const host = img.parentElement;
  if (!host) return null;
  let frame: HTMLElement | null = host;
  while (frame && (frame.clientHeight < MIN_FRAME_PX || frame.clientWidth < MIN_FRAME_PX)) frame = frame.parentElement;
  if (!frame) return null;
  const h = host.getBoundingClientRect();
  const f = frame.getBoundingClientRect();
  return {
    top: Math.round(f.top - h.top),
    left: Math.round(f.left - h.left),
    width: Math.round(f.width),
    height: Math.round(f.height),
  };
}

function previewStyle(box: Box | null, natural: { w: number; h: number } | null, rotation: number) {
  const transform = rotation ? `rotate(${rotation}deg)` : undefined;
  if (!box || !natural) return { maxWidth: '100%', maxHeight: '100%', transform };
  const aspect = natural.w / natural.h;
  const sideways = rotation % 180 !== 0;
  const shown = fitRect(box.width, box.height, sideways ? 1 / aspect : aspect);
  return {
    width: sideways ? shown.height : shown.width,
    height: sideways ? shown.width : shown.height,
    maxWidth: 'none',
    maxHeight: 'none',
    flex: 'none',
    transform,
  };
}

function sameBox(a: Box | null, b: Box | null) {
  return a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);
}

/**
 * Prévia instantânea: enquanto o <img> MJPEG do upstream ainda não tem o primeiro quadro (~8 s com a Thingino),
 * mostra por cima dele a última imagem do Frigate (baixa resolução, ~3 fps) e some com um fade quando o vídeo em
 * alta chega. Não mexe no componente do upstream: acha o <img> do stream dentro do próprio quadro e desenha a
 * prévia no mesmo contêiner (portal). Se a rota responder 404/erro (sem Frigate configurado), não aparece nada.
 */
export function CameraPreview({ printerId }: { printerId: number }) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [rotation, setRotation] = useState(0);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [ready, setReady] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const enabled = cameraPreviewEnabled();

  // Acompanha o <img> do stream: onde ele está, se já tem quadro e se deu erro.
  useEffect(() => {
    if (!enabled) return;
    let current: HTMLImageElement | null = null;
    const onError = () => setStreamFailed(true);
    const tick = () => {
      const root = anchorRef.current?.parentElement;
      const img = root?.querySelector<HTMLImageElement>(STREAM_IMG_SELECTOR) ?? null;
      if (img !== current) {
        current?.removeEventListener('error', onError);
        img?.addEventListener('error', onError);
        current = img;
        setStreamFailed(false);
      }
      setHost(img?.parentElement ?? null);
      const nextBox = img ? frameBox(img) : null;
      setBox((prev) => (sameBox(prev, nextBox) ? prev : nextBox));
      // reservado para o H.264 sem quadro ainda: a imagem transparente não conta, a prévia fica até o vídeo chegar
      const hasFrame = !!img && img.naturalWidth > 0 && !isWaitingForH264(img);
      const rot = rotationFromTransform(img?.style.transform);
      setRotation(rot);
      if (img && hasFrame) rememberCameraAspect(printerId, displayedAspect(img.naturalWidth, img.naturalHeight, rot));
      setReady(hasFrame);
      if (!hasFrame) setGone(false);
    };
    tick();
    const id = window.setInterval(tick, WATCH_INTERVAL_MS);
    return () => {
      window.clearInterval(id);
      current?.removeEventListener('error', onError);
    };
  }, [enabled, printerId]);

  // Depois do fade, desmonta a prévia (e para de baixar imagens).
  useEffect(() => {
    if (!ready) return;
    const id = window.setTimeout(() => setGone(true), FADE_MS + 50);
    return () => window.clearTimeout(id);
  }, [ready]);

  const wanted = enabled && !!host && !ready && !streamFailed && !unavailable;

  // Baixa a imagem da prévia em loop enquanto o vídeo não chega (fetch + blob: nada fica no cache do navegador).
  useEffect(() => {
    if (!wanted) return;
    let stopped = false;
    let timer: number | undefined;
    let failures = 0;
    let lastUrl: string | null = null;
    const ctrl = new AbortController();
    const next = async () => {
      if (stopped) return;
      if (document.visibilityState === 'hidden') {
        timer = window.setTimeout(next, 1000);
        return;
      }
      try {
        const url = withStreamToken(`/api/v1/custom/camera/stream/${printerId}/preview.jpg?t=${Date.now()}`);
        const resp = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
        if (resp.status === 404) {
          setUnavailable(true);
          return;
        }
        if (!resp.ok) throw new Error(String(resp.status));
        const blob = await resp.blob();
        if (stopped) return;
        const objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
        if (lastUrl) {
          const old = lastUrl;
          // revoga depois que o <img> já trocou para a imagem nova
          window.setTimeout(() => URL.revokeObjectURL(old), 1000);
        }
        lastUrl = objectUrl;
        failures = 0;
        timer = window.setTimeout(next, PREVIEW_INTERVAL_MS);
      } catch {
        if (stopped) return;
        failures += 1;
        if (failures >= MAX_FAILURES) {
          setUnavailable(true);
          return;
        }
        timer = window.setTimeout(next, 1000);
      }
    };
    next();
    return () => {
      stopped = true;
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [wanted, printerId]);

  const show = enabled && !!host && !!src && !streamFailed && !unavailable && !gone;
  return (
    <>
      <span ref={anchorRef} hidden data-custom-camera-preview-anchor="" />
      {show &&
        createPortal(
          <div
            data-testid="custom-camera-preview"
            aria-hidden="true"
            className="absolute z-[11] flex items-center justify-center overflow-hidden bg-black pointer-events-none"
            style={{
              ...(box ?? { top: 0, left: 0, width: '100%', height: '100%' }),
              opacity: ready ? 0 : 1,
              transition: `opacity ${FADE_MS}ms ease-out`,
            }}
          >
            <img
              src={src}
              alt=""
              className="object-contain select-none"
              draggable={false}
              onLoad={(e) => {
                const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
                if (w > 0 && h > 0 && (natural?.w !== w || natural?.h !== h)) setNatural({ w, h });
              }}
              // Mesmo tamanho e rotação que a alta vai ter: a imagem (640 px) é ampliada até caber no quadro; deitada
              // (90/270) o retângulo exibido tem a proporção invertida e a imagem é desenhada com largura/altura trocadas.
              style={previewStyle(box, natural, rotation)}
            />
            <div className="absolute top-2 left-2 flex items-center gap-1.5 rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white/80">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-bambu-green" />
              HD…
            </div>
          </div>,
          host,
        )}
    </>
  );
}
