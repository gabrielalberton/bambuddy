import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStreamImgRef } from '../../hooks/useStreamImgRef';
import { H264Live } from '../camera/H264Live';
import {
  SCOPE_ATTR,
  claimStreamImg,
  forgetIfReplaced,
  h264SocketUrl,
  h264Unavailable,
  isH264Active,
  isTakenOver,
  isWaitingForH264,
  liveAdjust,
  markAdopted,
  release,
  rememberedVideoSize,
  resetH264StateForTests,
  retryDelayMs,
  setH264Active,
  setH264DirectOverride,
  setH264Failing,
  setH264Override,
  supportedCodecs,
  takeOver,
  useH264Active,
} from '../camera/h264';

const MJPEG = '/api/v1/printers/1/camera/stream?fps=15&t=1&viewer=a';

/** O setup dos testes troca o localStorage por vi.fn() vazios: aqui ele guarda de verdade (tamanho do vídeo). */
function memoryStorage() {
  const data = new Map<string, string>();
  vi.mocked(localStorage.getItem).mockImplementation((key: string) => data.get(key) ?? null);
  vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => void data.set(key, String(value)));
  vi.mocked(localStorage.removeItem).mockImplementation((key: string) => void data.delete(key));
}

function resetStorage() {
  vi.mocked(localStorage.getItem).mockReset();
  vi.mocked(localStorage.setItem).mockReset();
  vi.mocked(localStorage.removeItem).mockReset();
}

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

describe('h264: abertura direta (o MJPEG nem abre)', () => {
  const fakeMse = class {
    static isTypeSupported = () => true;
  };
  let scope: HTMLDivElement;
  beforeEach(() => {
    setH264Override(true);
    vi.stubGlobal('MediaSource', fakeMse);
    memoryStorage();
    scope = document.createElement('div');
    scope.setAttribute(SCOPE_ATTR, '1');
    document.body.appendChild(scope);
  });
  afterEach(() => {
    scope.remove();
    resetH264StateForTests();
    resetStorage();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const streamImg = () => {
    const img = document.createElement('img');
    scope.appendChild(img);
    return img;
  };

  it('reserva o <img> do stream dentro do quadro com a imagem transparente do último vídeo', () => {
    localStorage.setItem('custom.h264Size', JSON.stringify({ 1: [2304, 1296] }));
    const img = streamImg();
    expect(claimStreamImg(img, MJPEG)).toBe(true);
    expect(img.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/);
    expect(decodeURIComponent(img.getAttribute('src')!)).toContain('width="2304" height="1296"');
    expect(isWaitingForH264(img)).toBe(true);
    // falhou: volta ao MJPEG com a URL guardada
    release(img);
    expect(img.getAttribute('src')).toBe(MJPEG);
    expect(isWaitingForH264(img)).toBe(false);
  });

  it('segue o upstream fora do quadro, em snapshot, na câmera nativa, desligado ou com o H.264 em falha', () => {
    const outside = document.createElement('img');
    document.body.appendChild(outside);
    expect(claimStreamImg(outside, MJPEG)).toBe(false);
    outside.remove();
    expect(claimStreamImg(streamImg(), '/api/v1/printers/1/camera/snapshot?t=1')).toBe(false);
    expect(claimStreamImg(streamImg(), '/api/v1/printers/1/camera/stream?native=true&fps=5')).toBe(false);
    setH264DirectOverride(false);
    expect(claimStreamImg(streamImg(), MJPEG)).toBe(false);
    setH264DirectOverride(null);
    setH264Failing(1, true);
    expect(claimStreamImg(streamImg(), MJPEG)).toBe(false);
    setH264Failing(1, false);
    vi.stubGlobal('MediaSource', undefined);
    expect(claimStreamImg(streamImg(), MJPEG)).toBe(false);
  });

  it('URL nova num <img> já sem MJPEG: só guarda para a volta', () => {
    const img = streamImg();
    claimStreamImg(img, MJPEG);
    const placeholder = img.getAttribute('src');
    const next = MJPEG.replace('t=1', 't=2');
    expect(claimStreamImg(img, next)).toBe(true);
    expect(img.getAttribute('src')).toBe(placeholder);
    release(img);
    expect(img.getAttribute('src')).toBe(next);
  });

  it('sem H264Live para assumir em 3 s, devolve o MJPEG', () => {
    vi.useFakeTimers();
    const lost = streamImg();
    const kept = streamImg();
    claimStreamImg(lost, MJPEG);
    claimStreamImg(kept, MJPEG);
    markAdopted(kept);
    vi.advanceTimersByTime(3100);
    expect(lost.getAttribute('src')).toBe(MJPEG);
    expect(isTakenOver(kept)).toBe(true);
  });

  it('lembra só tamanhos válidos', () => {
    localStorage.setItem('custom.h264Size', JSON.stringify({ 1: [0, 'x'] }));
    expect(rememberedVideoSize(1)).toEqual([1920, 1080]);
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

  it('abre direto pelo gancho do upstream: o MJPEG nunca recebe src e volta como reserva se o H.264 cair', async () => {
    memoryStorage();
    const seen: string[] = [];
    const srcSetter = vi.spyOn(HTMLImageElement.prototype, 'src', 'set');
    srcSetter.mockImplementation(function (this: HTMLImageElement, value: string) {
      seen.push(value);
      this.setAttribute('src', value);
    });
    function Upstream({ url }: { url: string }) {
      const imgRef = useRef<HTMLImageElement | null>(null);
      const attach = useStreamImgRef(imgRef, url);
      return (
        <div data-testid="video-area" className="relative">
          <img data-testid="stream" ref={attach} alt="Camera stream" />
        </div>
      );
    }
    const Page = ({ url }: { url: string }) => (
      <div {...{ [SCOPE_ATTR]: 1 }}>
        <Upstream url={url} />
        <H264Live printerId={1} />
      </div>
    );
    const { rerender } = render(<Page url={MJPEG} />);
    const img = screen.getByTestId('stream');
    expect(isWaitingForH264(img as HTMLImageElement)).toBe(true);
    await waitFor(() => expect(isH264Active(1)).toBe(true)); // checagem de travamento do upstream pausada
    const ws = await openSession();
    act(() => {
      ws.onmessage?.({ data: '{"type":"mse","value":"video/mp4; codecs=\\"avc1.4D0029\\""}' });
    });
    setVideoReady(screen.getByTestId('custom-h264-video'));
    await waitFor(() => expect(isWaitingForH264(img as HTMLImageElement)).toBe(false));
    expect(decodeURIComponent(img.getAttribute('src')!)).toContain('width="2304" height="1296"');
    expect(rememberedVideoSize(1)).toEqual([2304, 1296]);
    expect(seen.some((v) => v.includes('/camera/stream'))).toBe(false);

    // caiu depois de tocar: MJPEG de reserva e, até o H.264 voltar, URL nova do upstream abre o MJPEG
    act(() => ws.onclose?.({ code: 4502 }));
    expect(img.getAttribute('src')).toBe(MJPEG);
    const next = MJPEG.replace('t=1', 't=2');
    rerender(<Page url={next} />);
    expect(img.getAttribute('src')).toBe(next);
    srcSetter.mockRestore();
    resetStorage();
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
