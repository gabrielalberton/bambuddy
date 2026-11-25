import { useSyncExternalStore } from 'react';

/**
 * Vídeo ao vivo em H.264 via go2rtc (custom/docs/camera-h264.md): interruptor, estado compartilhado e as partes
 * puras do player (testáveis sem MediaSource).
 *
 * `localStorage['custom.h264'] = 'off' | 'on'` força; padrão ligado fora dos testes do vitest.
 * `localStorage['custom.h264Direct'] = 'off'` volta a abrir o MJPEG junto (o H.264 assume quando tiver quadro).
 */
let override: boolean | null = null;
let directOverride: boolean | null = null;

export function setH264Override(value: boolean | null) {
  override = value;
}

export function setH264DirectOverride(value: boolean | null) {
  directOverride = value;
}

/** Abre o H.264 sem abrir o MJPEG antes (o `<img>` do upstream já nasce com a imagem transparente). */
export function h264DirectEnabled(): boolean {
  if (directOverride !== null) return directOverride;
  try {
    if (localStorage.getItem('custom.h264Direct') === 'off') return false;
  } catch {
    // localStorage indisponível: segue o padrão
  }
  return true;
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

/** Atributo do `<img>` reservado para o H.264 que ainda não tem quadro: a prévia do Frigate continua por cima. */
export const WAITING_ATTR = 'data-custom-h264-wait';

/** Reservado para o H.264 e sem vídeo ainda (a imagem transparente não conta como quadro). */
export function isWaitingForH264(img: HTMLImageElement): boolean {
  return img.hasAttribute(WAITING_ATTR) && isTakenOver(img);
}

function setPlaceholder(img: HTMLImageElement, width: number, height: number) {
  const placeholder = placeholderSrc(width, height);
  img.setAttribute('data-custom-h264', placeholder);
  img.src = placeholder;
}

/** Para o MJPEG (o navegador fecha a conexão, o backend encerra o ffmpeg) trocando o `src` pela imagem transparente. */
export function takeOver(img: HTMLImageElement, width: number, height: number): boolean {
  const src = img.getAttribute('src') ?? '';
  if (!src.includes('/camera/stream') || src.includes('native=true')) return false;
  saved.set(img, src);
  setPlaceholder(img, width, height);
  return true;
}

/** Devolve o MJPEG ao `<img>` (se o upstream não trocou o `src` nesse meio-tempo). */
export function release(img: HTMLImageElement) {
  if (!img.hasAttribute('data-custom-h264')) return;
  const mine = isTakenOver(img);
  img.removeAttribute('data-custom-h264');
  img.removeAttribute(WAITING_ATTR);
  const src = saved.get(img);
  saved.delete(img);
  if (mine && src && img.isConnected) img.src = src;
}

/** O upstream trocou o `src` (snapshot, atualizar): esquece a troca sem mexer no que ele pôs. */
export function forgetIfReplaced(img: HTMLImageElement) {
  if (img.hasAttribute('data-custom-h264') && !isTakenOver(img)) {
    img.removeAttribute('data-custom-h264');
    img.removeAttribute(WAITING_ATTR);
    saved.delete(img);
  }
}

// --- abertura direta: o MJPEG nem começa -----------------------------------------------------------------------

/** Atributo que o `CameraOrTwin` põe no seu contêiner (valor: id da impressora); só ali há um `H264Live`. */
export const SCOPE_ATTR = 'data-custom-h264-scope';

/** Sem `H264Live` assumindo o `<img>` reservado nesse prazo (não deveria acontecer): devolve o MJPEG. */
const ADOPT_TIMEOUT_MS = 3000;
const SIZE_KEY = 'custom.h264Size';
const DEFAULT_SIZE: [number, number] = [1920, 1080];

const adopted = new WeakSet<HTMLImageElement>();
const failing = new Set<number>();

/** Tamanho do último vídeo desta impressora: a imagem transparente já nasce com a proporção certa. */
export function rememberedVideoSize(printerId: number): [number, number] {
  try {
    const size = (JSON.parse(localStorage.getItem(SIZE_KEY) || '{}') as Record<string, unknown>)[printerId];
    if (Array.isArray(size) && size.length === 2 && size.every((n) => Number.isInteger(n) && n > 0 && n <= 8192)) {
      return [size[0], size[1]];
    }
  } catch {
    // sem localStorage: 16:9
  }
  return DEFAULT_SIZE;
}

function rememberVideoSize(printerId: number, width: number, height: number) {
  try {
    const all = JSON.parse(localStorage.getItem(SIZE_KEY) || '{}') as Record<string, unknown>;
    all[printerId] = [width, height];
    localStorage.setItem(SIZE_KEY, JSON.stringify(all));
  } catch {
    // sem localStorage
  }
}

/** A última sessão desta impressora caiu antes de ter quadro: o MJPEG volta a abrir até o H.264 ter quadro de novo. */
export function setH264Failing(printerId: number, on: boolean) {
  if (on) failing.add(printerId);
  else failing.delete(printerId);
}

/** O `H264Live` do quadro assumiu o `<img>` reservado. */
export function markAdopted(img: HTMLImageElement) {
  adopted.add(img);
}

/**
 * Gancho do `useStreamImgRef` do upstream: em vez de abrir o MJPEG, reserva o `<img>` do stream para o H.264 (imagem
 * transparente com o tamanho do último vídeo; a prévia do Frigate fica por cima até o vídeo ter quadro). Devolve
 * `false` quando o upstream deve seguir normal: fora de um `CameraOrTwin`, câmera nativa, snapshot, H.264 desligado,
 * indisponível ou em falha. Se o `<img>` já está reservado, só atualiza a URL guardada para a volta ao MJPEG.
 */
export function claimStreamImg(img: HTMLImageElement, src: string): boolean {
  if (!src.includes('/camera/stream') || src.includes('native=true')) return false;
  const scope = img.closest(`[${SCOPE_ATTR}]`);
  const printerId = Number(scope?.getAttribute(SCOPE_ATTR));
  if (!scope || !Number.isInteger(printerId) || printerId <= 0) return false;
  if (isTakenOver(img)) {
    saved.set(img, src);
    return true;
  }
  if (!h264Enabled() || !h264DirectEnabled() || !mediaSourceCtor() || h264Unavailable() || failing.has(printerId)) {
    return false;
  }
  saved.set(img, src);
  img.setAttribute(WAITING_ATTR, '');
  const [width, height] = rememberedVideoSize(printerId);
  setPlaceholder(img, width, height);
  window.setTimeout(() => {
    if (img.isConnected && isWaitingForH264(img) && !adopted.has(img)) release(img);
  }, ADOPT_TIMEOUT_MS);
  return true;
}

/** O vídeo tem quadro: a prévia pode sair e a imagem transparente fica com o tamanho real do vídeo. */
export function showH264(img: HTMLImageElement, printerId: number, width: number, height: number) {
  img.removeAttribute(WAITING_ATTR);
  const [w, h] = rememberedVideoSize(printerId);
  if (w !== width || h !== height) rememberVideoSize(printerId, width, height);
  if (img.getAttribute('data-custom-h264') !== placeholderSrc(width, height)) setPlaceholder(img, width, height);
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
  failing.clear();
  override = null;
  directOverride = null;
}
