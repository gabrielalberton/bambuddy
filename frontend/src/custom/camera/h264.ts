import { useSyncExternalStore } from 'react';

/**
 * Vídeo ao vivo em H.264 via go2rtc (custom/docs/camera-h264.md): interruptor, estado compartilhado e as partes
 * puras do player (testáveis sem MediaSource).
 *
 * `localStorage['custom.h264'] = 'off' | 'on'` força; padrão ligado fora dos testes do vitest.
 */
let override: boolean | null = null;

export function setH264Override(value: boolean | null) {
  override = value;
}

export function h264Enabled(): boolean {
  if (override !== null) return override;
  try {
    const stored = localStorage.getItem('custom.h264');
    if (stored === 'off') return false;
    if (stored === 'on') return true;
  } catch {
    // localStorage indisponível: segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}

type MediaSourceCtor = typeof MediaSource;

/** MediaSource do navegador (ManagedMediaSource no Safari 17+, como o player do go2rtc). */
export function mediaSourceCtor(): { ctor: MediaSourceCtor; managed: boolean } | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { ManagedMediaSource?: MediaSourceCtor; MediaSource?: MediaSourceCtor };
  if (w.ManagedMediaSource) return { ctor: w.ManagedMediaSource, managed: true };
  if (w.MediaSource) return { ctor: w.MediaSource, managed: false };
  return null;
}

/** Só vídeo H.264 (a lista do video-rtc.js do go2rtc + Main/Baseline): o áudio da câmera não interessa aqui. */
const CODECS = ['avc1.640029', 'avc1.64002A', 'avc1.640033', 'avc1.4D0029', 'avc1.42E01E'];

export function supportedCodecs(isTypeSupported: (type: string) => boolean): string {
  return CODECS.filter((codec) => {
    try {
      return isTypeSupported(`video/mp4; codecs="${codec}"`);
    } catch {
      return false;
    }
  }).join(',');
}

/** Códigos de fechamento do backend (backend/app/custom/camera_h264.py). */
export const CLOSE_UNAUTHORIZED = 4401;
export const CLOSE_UNAVAILABLE = 4404;

export function h264SocketUrl(printerId: number, withToken: (url: string) => string, loc: Location = window.location): string {
  const path = withToken(`/api/v1/custom/camera/h264/${printerId}/ws`);
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${loc.host}${path}`;
}

/** Espera até a próxima tentativa (a falha n começa em 1). */
export function retryDelayMs(failures: number): number {
  const steps = [2000, 5000, 15000, 30000];
  return steps[Math.min(Math.max(failures, 1), steps.length) - 1];
}

/**
 * Mantém o vídeo perto do vivo, como o player do go2rtc: guarda só os últimos 5 s, pula para o começo da janela se
 * ficou para trás e ajusta a velocidade pelo atraso (ritmo 1 com ~1 s de folga, nunca abaixo de 0,5x para a abertura não
 * parecer câmera lenta). Atraso grande: pula para perto do fim.
 */
export function liveAdjust(start0: number, end: number, current: number) {
  const keepFrom = end - 5;
  const removeUpTo = keepFrom > start0 ? keepFrom : null;
  let seekTo: number | null = null;
  if (end - current > 3) seekTo = end - 0.5;
  else if (current < keepFrom) seekTo = keepFrom;
  const gap = end - (seekTo ?? current);
  const rate = Math.min(Math.max(gap, 0.5), 4);
  return { removeUpTo, seekTo, rate };
}

// --- troca do <img> MJPEG do upstream -------------------------------------------------------------------------

/** O `<img>` do stream do upstream; depois da troca ele perde o `/camera/stream` do `src` e fica marcado. */
export const STREAM_IMG_SELECTOR = 'img[src*="/camera/stream"]:not([src*="native=true"]), img[data-custom-h264]';

const saved = new WeakMap<HTMLImageElement, string>();

/** Imagem transparente com o tamanho do vídeo: o `<img>` do upstream mantém layout, zoom/arrasto e proporção. */
export function placeholderSrc(width: number, height: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"/>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function isTakenOver(img: HTMLImageElement): boolean {
  return img.hasAttribute('data-custom-h264') && img.getAttribute('src') === img.getAttribute('data-custom-h264');
}

/** Para o MJPEG (o navegador fecha a conexão, o backend encerra o ffmpeg) trocando o `src` pela imagem transparente. */
export function takeOver(img: HTMLImageElement, width: number, height: number): boolean {
  const src = img.getAttribute('src') ?? '';
  if (!src.includes('/camera/stream') || src.includes('native=true')) return false;
  const placeholder = placeholderSrc(width, height);
  saved.set(img, src);
  img.setAttribute('data-custom-h264', placeholder);
  img.src = placeholder;
  return true;
}

/** Devolve o MJPEG ao `<img>` (se o upstream não trocou o `src` nesse meio-tempo). */
export function release(img: HTMLImageElement) {
  if (!img.hasAttribute('data-custom-h264')) return;
  const mine = isTakenOver(img);
  img.removeAttribute('data-custom-h264');
  const src = saved.get(img);
  saved.delete(img);
  if (mine && src && img.isConnected) img.src = src;
}

/** O upstream trocou o `src` (snapshot, atualizar): esquece a troca sem mexer no que ele pôs. */
export function forgetIfReplaced(img: HTMLImageElement) {
  if (img.hasAttribute('data-custom-h264') && !isTakenOver(img)) {
    img.removeAttribute('data-custom-h264');
    saved.delete(img);
  }
}

// --- estado compartilhado: pausa a checagem de travamento do MJPEG no upstream ---------------------------------

const active = new Map<number, number>();
const listeners = new Set<() => void>();

export function setH264Active(printerId: number, on: boolean) {
  const count = Math.max(0, (active.get(printerId) ?? 0) + (on ? 1 : -1));
  if (count) active.set(printerId, count);
  else active.delete(printerId);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isH264Active(printerId: number): boolean {
  return (active.get(printerId) ?? 0) > 0;
}

/** Verdadeiro enquanto o H.264 substitui o MJPEG desta impressora (o `/camera/status` do upstream fica inativo). */
export function useH264Active(printerId: number): boolean {
  return useSyncExternalStore(subscribe, () => isH264Active(printerId), () => false);
}

/** O backend respondeu 4404 (sem `BAMBUDDY_CUSTOM_H264_WS_URL`): não tenta de novo até recarregar a página. */
let unavailable = false;

export function markH264Unavailable() {
  unavailable = true;
}

export function h264Unavailable(): boolean {
  return unavailable;
}

export function resetH264StateForTests() {
  unavailable = false;
  active.clear();
  override = null;
}
