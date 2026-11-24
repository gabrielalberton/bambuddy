import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { H264Live } from '../camera/H264Live';
import {
  forgetIfReplaced,
  h264SocketUrl,
  h264Unavailable,
  isH264Active,
  isTakenOver,
  liveAdjust,
  release,
  resetH264StateForTests,
  retryDelayMs,
  setH264Active,
  setH264Override,
  supportedCodecs,
  takeOver,
  useH264Active,
} from '../camera/h264';

const MJPEG = '/api/v1/printers/1/camera/stream?fps=15&t=1&viewer=a';

describe('h264: partes puras', () => {
  afterEach(() => resetH264StateForTests());

  it('pede só os codecs H.264 que o navegador toca', () => {
    expect(supportedCodecs((t) => t.includes('avc1.64'))).toBe('avc1.640029,avc1.64002A,avc1.640033');
    expect(supportedCodecs(() => false)).toBe('');
  });

  it('monta a URL do WebSocket com o token de stream e o esquema da página', () => {
    const withToken = (u: string) => `${u}?token=abc`;
    expect(h264SocketUrl(1, withToken, { protocol: 'https:', host: 'bambu.example' } as Location)).toBe(
      'wss://bambu.example/api/v1/custom/camera/h264/1/ws?token=abc',
    );
    expect(h264SocketUrl(2, (u) => u, { protocol: 'http:', host: 'nuc:8000' } as Location)).toBe(
      'ws://nuc:8000/api/v1/custom/camera/h264/2/ws',
    );
  });

  it('mantém o vídeo perto do vivo', () => {
    expect(liveAdjust(0, 2, 1)).toEqual({ removeUpTo: null, seekTo: null, rate: 1 });
    expect(liveAdjust(0, 12, 11.5)).toEqual({ removeUpTo: 7, seekTo: null, rate: 0.5 });
    const late = liveAdjust(0, 20, 10);
    expect(late.seekTo).toBe(19.5);
    expect(late.rate).toBeCloseTo(0.5);
    expect(liveAdjust(0, 2.5, 0).rate).toBe(2.5);
    expect(liveAdjust(0, 0.1, 0).rate).toBe(0.5); // abertura: no máximo meia velocidade
  });

  it('espera mais a cada falha seguida', () => {
    expect([1, 2, 3, 4, 9].map(retryDelayMs)).toEqual([2000, 5000, 15000, 30000, 30000]);
  });

  it('troca o MJPEG por uma imagem transparente do tamanho do vídeo e devolve depois', () => {
    const img = document.createElement('img');
    img.setAttribute('src', MJPEG);
    document.body.appendChild(img);
    expect(takeOver(img, 2304, 1296)).toBe(true);
    expect(img.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/);
    expect(decodeURIComponent(img.getAttribute('src')!)).toContain('width="2304" height="1296"');
    expect(isTakenOver(img)).toBe(true);
    release(img);
    expect(img.getAttribute('src')).toBe(MJPEG);
    expect(img.hasAttribute('data-custom-h264')).toBe(false);
    img.remove();
  });

  it('não devolve o MJPEG se o upstream já trocou o src (snapshot, atualizar)', () => {
    const img = document.createElement('img');
    img.setAttribute('src', MJPEG);
    takeOver(img, 1280, 720);
    img.setAttribute('src', '/api/v1/printers/1/camera/snapshot');
    forgetIfReplaced(img);
    expect(img.hasAttribute('data-custom-h264')).toBe(false);
    release(img);
    expect(img.getAttribute('src')).toBe('/api/v1/printers/1/camera/snapshot');
  });

  it('não mexe na câmera nativa da A1', () => {
    const img = document.createElement('img');
    img.setAttribute('src', '/api/v1/printers/1/camera/stream?native=true&fps=5');
    expect(takeOver(img, 1280, 720)).toBe(false);
  });

  it('avisa quem pausa a checagem de travamento do upstream', () => {
    const { result } = renderHook(() => useH264Active(1));
    expect(result.current).toBe(false);
    act(() => setH264Active(1, true));
    expect(result.current).toBe(true);
    act(() => setH264Active(1, false));
    expect(result.current).toBe(false);
  });
});

// --- player completo com WebSocket e MediaSource falsos ---------------------------------------------------------

class FakeSourceBuffer extends EventTarget {
  mode = 'segments';
  updating = false;
  buffered = { length: 0, start: () => 0, end: () => 0 };
  appended: number[] = [];
  appendBuffer(data: Uint8Array) {
    this.appended.push(data.byteLength);
  }
  remove() {}
}

class FakeMediaSource extends EventTarget {
  static isTypeSupported = (t: string) => t.includes('avc1');
  static last: FakeMediaSource | null = null;
  types: string[] = [];
  sb = new FakeSourceBuffer();
  constructor() {
    super();
    FakeMediaSource.last = this;
  }
  addSourceBuffer(type: string) {
    this.types.push(type);
    return this.sb;
  }
}

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  binaryType = 'blob';
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(text: string) {
    this.sent.push(text);
  }
  close() {
    this.readyState = 3;
  }
}

function Frame() {
  return (
    <div>
      <div data-testid="video-area" className="relative">
        <img data-testid="stream" src={MJPEG} alt="Camera stream" />
      </div>
      <H264Live printerId={1} />
    </div>
  );
}

function setVideoReady(video: HTMLElement) {
  Object.defineProperty(video, 'readyState', { configurable: true, get: () => 4 });
  Object.defineProperty(video, 'videoWidth', { configurable: true, get: () => 2304 });
  Object.defineProperty(video, 'videoHeight', { configurable: true, get: () => 1296 });
}

async function openSession() {
  await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
  const ws = FakeWebSocket.instances[0];
  act(() => {
    ws.readyState = 1;
    ws.onopen?.();
  });
  act(() => {
    FakeMediaSource.last!.dispatchEvent(new Event('sourceopen'));
  });
  return ws;
}

describe('H264Live (vídeo H.264 no lugar do MJPEG)', () => {
  beforeEach(() => {
    setH264Override(true);
    FakeWebSocket.instances = [];
    FakeMediaSource.last = null;
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('MediaSource', FakeMediaSource);
    URL.createObjectURL = vi.fn(() => 'blob:mse');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined);
  });
  afterEach(() => {
    resetH264StateForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('toca o H.264, para o MJPEG quando há quadro e devolve o MJPEG se a conexão cair', async () => {
    render(<Frame />);
    const ws = await openSession();
    expect(ws.url).toContain('/api/v1/custom/camera/h264/1/ws');
    expect(JSON.parse(ws.sent[0])).toEqual({ type: 'mse', value: 'avc1.640029,avc1.64002A,avc1.640033,avc1.4D0029,avc1.42E01E' });

    act(() => {
      ws.onmessage?.({ data: '{"type":"mse","value":"video/mp4; codecs=\\"avc1.4D0029\\""}' });
      ws.onmessage?.({ data: new Uint8Array(16).buffer });
    });
    expect(FakeMediaSource.last!.types).toEqual(['video/mp4; codecs="avc1.4D0029"']);
    expect(FakeMediaSource.last!.sb.appended).toEqual([16]);

    const img = screen.getByTestId('stream');
    expect(img.getAttribute('src')).toBe(MJPEG); // sem quadro ainda: MJPEG continua
    const video = screen.getByTestId('custom-h264-video');
    expect(screen.getByTestId('video-area').contains(video)).toBe(true);
    setVideoReady(video);
    await waitFor(() => expect(img.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/));
    expect(isH264Active(1)).toBe(true);

    act(() => ws.onclose?.({ code: 4502 }));
    expect(img.getAttribute('src')).toBe(MJPEG);
    expect(isH264Active(1)).toBe(false);
  });

  it('sem a rota configurada (4404) fica no MJPEG e não tenta de novo', async () => {
    render(<Frame />);
    const ws = await openSession();
    act(() => ws.onclose?.({ code: 4404 }));
    expect(h264Unavailable()).toBe(true);
    await waitFor(() => expect(screen.queryByTestId('custom-h264-video')).toBeNull());
    await new Promise((r) => setTimeout(r, 300));
    expect(FakeWebSocket.instances.length).toBe(1);
    expect(screen.getByTestId('stream').getAttribute('src')).toBe(MJPEG);
  });

  it('desligado (ou sem MediaSource) não abre conexão nem mexe no <img>', async () => {
    setH264Override(false);
    const { unmount } = render(<Frame />);
    await new Promise((r) => setTimeout(r, 300));
    expect(FakeWebSocket.instances.length).toBe(0);
    unmount();

    setH264Override(true);
    vi.stubGlobal('MediaSource', undefined);
    render(<Frame />);
    await new Promise((r) => setTimeout(r, 300));
    expect(FakeWebSocket.instances.length).toBe(0);
    expect(screen.getByTestId('stream').getAttribute('src')).toBe(MJPEG);
  });

  it('devolve o MJPEG ao desmontar', async () => {
    const { unmount, container } = render(<Frame />);
    const ws = await openSession();
    act(() => {
      ws.onmessage?.({ data: '{"type":"mse","value":"video/mp4; codecs=\\"avc1.4D0029\\""}' });
    });
    const img = screen.getByTestId('stream');
    setVideoReady(screen.getByTestId('custom-h264-video'));
    await waitFor(() => expect(isTakenOver(img as HTMLImageElement)).toBe(true));
    const detached = container.querySelector('img')!;
    unmount();
    expect(isH264Active(1)).toBe(false);
    expect(detached.hasAttribute('data-custom-h264')).toBe(false);
  });
});
