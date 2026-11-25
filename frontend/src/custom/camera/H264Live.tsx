import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { withStreamToken } from '../../api/client';
import {
  CLOSE_UNAVAILABLE,
  STREAM_IMG_SELECTOR,
  forgetIfReplaced,
  h264Enabled,
  h264SocketUrl,
  h264Unavailable,
  isTakenOver,
  isWaitingForH264,
  liveAdjust,
  markAdopted,
  markH264Unavailable,
  mediaSourceCtor,
  release,
  retryDelayMs,
  setH264Active,
  setH264Failing,
  showH264,
  supportedCodecs,
  takeOver,
} from './h264';

const WATCH_MS = 150;
/** Sem dado novo depois de começar: a conexão travou, reconecta. */
const STALL_MS = 8000;
/** Sem primeiro quadro (o quadro-chave da Thingino vem a cada 2 s): desiste desta tentativa. */
const START_TIMEOUT_MS = 15000;
/** Idem com o MJPEG nem aberto (só a prévia do Frigate na tela): volta ao MJPEG mais cedo. */
const DIRECT_START_TIMEOUT_MS = 8000;
const MAX_PENDING_BYTES = 4 * 1024 * 1024;

type Layout = { box: { left: number; top: number; width: number; height: number } | null; transform: string };

/** Mesmo retângulo de layout (antes do `transform`) e mesmo `transform` do `<img>` do upstream: zoom, arrasto e rotação. */
function layoutOf(img: HTMLImageElement, host: HTMLElement): Layout {
  if (!img.offsetWidth || !img.offsetHeight) return { box: null, transform: '' };
  if (img.offsetParent === host) {
    return {
      box: { left: img.offsetLeft, top: img.offsetTop, width: img.offsetWidth, height: img.offsetHeight },
      transform: img.style.transform,
    };
  }
  const h = host.getBoundingClientRect();
  const r = img.getBoundingClientRect();
  return { box: { left: r.left - h.left, top: r.top - h.top, width: r.width, height: r.height }, transform: '' };
}

function sameLayout(a: Layout, b: Layout) {
  const x = a.box;
  const y = b.box;
  const boxEqual = x === y || (!!x && !!y && x.left === y.left && x.top === y.top && x.width === y.width && x.height === y.height);
  return boxEqual && a.transform === b.transform;
}

/** Último quadro como pôster: ao voltar do segundo plano o vídeo não fica preto enquanto reconecta. */
function rememberFrame(video: HTMLVideoElement) {
  if (!video.videoWidth || video.readyState < 2) return;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0);
    video.poster = canvas.toDataURL('image/jpeg', 0.7);
  } catch {
    // sem pôster
  }
}

/**
 * Vídeo ao vivo em H.264 (go2rtc via backend, ~1,5 Mbps em resolução cheia) no lugar do MJPEG do upstream
 * (custom/docs/camera-h264.md). Toca atrás do `<img>` do upstream, que fica com uma imagem transparente do mesmo
 * tamanho: o vídeo aparece no mesmo lugar, com o mesmo zoom/rotação. Normalmente o `<img>` já nasce assim (gancho no
 * `useStreamImgRef`, o MJPEG nem abre); senão a troca acontece no 1º quadro. Se o H.264 cair, devolve o MJPEG e tenta
 * de novo depois.
 */
export function H264Live({ printerId }: { printerId: number }) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const owned = useRef(new Set<HTMLImageElement>());
  const shown = useRef(new WeakSet<HTMLImageElement>());
  const activeRef = useRef(false);
  const failures = useRef(0);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [layout, setLayout] = useState<Layout>({ box: null, transform: '' });
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden');
  const [attempt, setAttempt] = useState(0);
  const [stopped, setStopped] = useState(false);
  const enabled = h264Enabled() && !!mediaSourceCtor() && !h264Unavailable() && !stopped;

  const releaseAll = () => {
    owned.current.forEach((img) => release(img));
    owned.current.clear();
    if (activeRef.current) {
      activeRef.current = false;
      setH264Active(printerId, false);
    }
  };
  const releaseRef = useRef(releaseAll);
  releaseRef.current = releaseAll;

  /** `<img>` já sem MJPEG (reservado na abertura ou trocado depois do 1º quadro): pausa a checagem do upstream. */
  const own = (img: HTMLImageElement) => {
    if (!owned.current.has(img)) {
      owned.current.add(img);
      markAdopted(img);
    }
    if (!activeRef.current) {
      activeRef.current = true;
      setH264Active(printerId, true);
    }
  };
  const ownRef = useRef(own);
  ownRef.current = own;

  // Devolve o MJPEG ao desmontar ou desligar.
  useEffect(() => {
    if (!enabled) return;
    return () => releaseRef.current();
  }, [enabled, printerId]);

  useEffect(() => {
    const onVisibility = () => {
      const hidden = document.visibilityState === 'hidden';
      if (hidden && videoRef.current) rememberFrame(videoRef.current);
      setVisible(!hidden);
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  // Acompanha o <img> do upstream: onde desenhar o vídeo e com que transform.
  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      const root = anchorRef.current?.parentElement;
      const img = root?.querySelector<HTMLImageElement>(STREAM_IMG_SELECTOR) ?? null;
      const nextHost = img?.parentElement ?? null;
      setHost((prev) => (prev === nextHost ? prev : nextHost));
      if (!img || !nextHost) {
        if (owned.current.size) releaseRef.current();
        return;
      }
      forgetIfReplaced(img);
      if (isTakenOver(img)) ownRef.current(img);
      const next = layoutOf(img, nextHost);
      setLayout((prev) => (sameLayout(prev, next) ? prev : next));
    };
    tick();
    const id = window.setInterval(tick, WATCH_MS);
    return () => window.clearInterval(id);
  }, [enabled]);

  // O vídeo é desenhado com z-index -1 dentro do quadro: atrás do <img> e dos avisos/botões do upstream.
  useEffect(() => {
    if (!host) return;
    const previous = host.style.isolation;
    host.style.isolation = 'isolate';
    return () => {
      host.style.isolation = previous;
    };
  }, [host]);

  // Sessão: WebSocket do backend -> MediaSource -> <video>; troca o MJPEG quando há quadro.
  useEffect(() => {
    const video = videoRef.current;
    const media = mediaSourceCtor();
    if (!enabled || !host || !visible || !video || !media) return;
    let disposed = false;
    let ready = false;
    let lastData = Date.now();
    const started = Date.now();
    let retryTimer: number | undefined;
    let objectUrl: string | null = null;
    let sb: SourceBuffer | null = null;
    let pending: Uint8Array[] = [];
    let pendingBytes = 0;
    let ms: MediaSource;
    let ws: WebSocket;
    try {
      ms = new media.ctor();
      ws = new WebSocket(h264SocketUrl(printerId, withStreamToken));
    } catch {
      markH264Unavailable();
      releaseRef.current();
      setStopped(true);
      return;
    }
    ws.binaryType = 'arraybuffer';
    video.muted = true;

    const dispose = () => {
      if (disposed) return;
      disposed = true;
      window.clearInterval(watch);
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      video.pause();
      video.removeAttribute('src');
      video.srcObject = null;
      video.load();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };

    const fail = (retry: boolean) => {
      if (disposed) return;
      dispose();
      // antes de devolver o MJPEG: o gancho do upstream não reserva de novo enquanto o H.264 não voltar
      if (retry) setH264Failing(printerId, true);
      else markH264Unavailable();
      releaseRef.current();
      if (!retry) {
        setStopped(true);
        return;
      }
      failures.current += 1;
      retryTimer = window.setTimeout(() => setAttempt((n) => n + 1), retryDelayMs(failures.current));
    };

    const append = (chunk: Uint8Array) => {
      try {
        sb?.appendBuffer(chunk as BufferSource);
      } catch {
        fail(true);
      }
    };

    const onUpdateEnd = () => {
      if (!sb || disposed) return;
      if (!sb.updating && pending.length) {
        const all = new Uint8Array(pendingBytes);
        let offset = 0;
        for (const part of pending) {
          all.set(part, offset);
          offset += part.byteLength;
        }
        pending = [];
        pendingBytes = 0;
        append(all);
      }
      // Ajusta o ritmo a cada fragmento, mesmo com outro append em andamento (página ocupada acumula fila);
      // só a limpeza do buffer espera o SourceBuffer ficar livre.
      if (!sb.buffered.length) return;
      const start0 = sb.buffered.start(0);
      const { removeUpTo, seekTo, rate } = liveAdjust(start0, sb.buffered.end(sb.buffered.length - 1), video.currentTime);
      try {
        if (removeUpTo !== null && !sb.updating) sb.remove(start0, removeUpTo);
        if (seekTo !== null) video.currentTime = seekTo;
        video.playbackRate = rate;
      } catch {
        // tenta de novo no próximo fragmento
      }
    };

    ws.onopen = () => {
      ms.addEventListener(
        'sourceopen',
        () => {
          if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
          }
          const codecs = supportedCodecs((type) => media.ctor.isTypeSupported(type));
          if (!codecs) {
            fail(false);
            return;
          }
          ws.send(JSON.stringify({ type: 'mse', value: codecs }));
        },
        { once: true },
      );
      if (media.managed) {
        (video as HTMLVideoElement & { disableRemotePlayback: boolean }).disableRemotePlayback = true;
        video.srcObject = ms as unknown as MediaProvider;
      } else {
        objectUrl = URL.createObjectURL(ms);
        video.src = objectUrl;
      }
      video.play().catch(() => undefined);
    };

    ws.onmessage = (event: MessageEvent) => {
      if (disposed) return;
      if (typeof event.data === 'string') {
        let msg: { type?: string; value?: string };
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type === 'mse' && !sb && typeof msg.value === 'string') {
          try {
            sb = ms.addSourceBuffer(msg.value);
            sb.mode = 'segments';
            sb.addEventListener('updateend', onUpdateEnd);
          } catch {
            fail(false); // o navegador não toca o que o go2rtc escolheu
          }
        } else if (msg.type === 'error') {
          fail(true);
        }
        return;
      }
      lastData = Date.now();
      if (!sb) return;
      const chunk = new Uint8Array(event.data as ArrayBuffer);
      if (sb.updating || pending.length) {
        pending.push(chunk);
        pendingBytes += chunk.byteLength;
        if (pendingBytes > MAX_PENDING_BYTES) fail(true);
      } else {
        append(chunk);
      }
    };

    ws.onclose = (event: CloseEvent) => {
      if (event.code === CLOSE_UNAVAILABLE) {
        markH264Unavailable();
        fail(false);
      } else {
        fail(true);
      }
    };

    const watch = window.setInterval(() => {
      if (disposed) return;
      const now = Date.now();
      if (!ready && video.readyState >= 2 && video.videoWidth > 0) {
        ready = true;
        failures.current = 0;
        setH264Failing(printerId, false);
      }
      const root = anchorRef.current?.parentElement;
      const img = root?.querySelector<HTMLImageElement>(STREAM_IMG_SELECTOR) ?? null;
      if (ready) {
        if (img && (isTakenOver(img) || takeOver(img, video.videoWidth, video.videoHeight))) {
          ownRef.current(img);
          if (!shown.current.has(img) || isWaitingForH264(img)) {
            shown.current.add(img);
            showH264(img, printerId, video.videoWidth, video.videoHeight);
          }
        }
        if (video.paused) video.play().catch(() => undefined);
        if (now - lastData > STALL_MS) fail(true);
      } else if (now - started > (img && isWaitingForH264(img) ? DIRECT_START_TIMEOUT_MS : START_TIMEOUT_MS)) {
        fail(true);
      }
    }, WATCH_MS);

    return () => {
      window.clearTimeout(retryTimer);
      dispose();
    };
  }, [enabled, host, visible, attempt, printerId]);

  const style: CSSProperties = {
    position: 'absolute',
    zIndex: -1,
    ...(layout.box ?? { left: 0, top: 0, width: '100%', height: '100%' }),
    transform: layout.box ? layout.transform || undefined : undefined,
    // o preflight do Tailwind põe `max-width: 100%; height: auto` em <video>: com a câmera deitada (90/270) o
    // retângulo sem rotação é mais largo que o quadro e seria espremido (o <img> do upstream também recebe `none`)
    maxWidth: 'none',
    maxHeight: 'none',
    objectFit: 'contain',
    background: 'transparent',
    pointerEvents: 'none',
  };

  return (
    <>
      <span ref={anchorRef} hidden data-custom-h264-anchor="" />
      {enabled &&
        host &&
        createPortal(
          <video
            ref={videoRef}
            data-testid="custom-h264-video"
            aria-hidden="true"
            muted
            autoPlay
            playsInline
            disablePictureInPicture
            style={style}
          />,
          host,
        )}
    </>
  );
}
