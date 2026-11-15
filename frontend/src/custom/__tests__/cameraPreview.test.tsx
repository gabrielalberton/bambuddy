import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CameraPreview } from '../camera/CameraPreview';
import { setCameraPreviewOverride } from '../camera/previewFlags';

function Frame({ withStream = true }: { withStream?: boolean }) {
  return (
    <div>
      <div data-testid="video-area" className="relative">
        {withStream && <img data-testid="stream" src="/api/v1/printers/1/camera/stream?fps=15" alt="" />}
      </div>
      <CameraPreview printerId={1} />
    </div>
  );
}

function setNaturalWidth(img: HTMLElement, value: number) {
  Object.defineProperty(img, 'naturalWidth', { configurable: true, get: () => value });
}

describe('CameraPreview (prévia instantânea da câmera)', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    setCameraPreviewOverride(true);
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    URL.createObjectURL = vi.fn(() => 'blob:preview');
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    setCameraPreviewOverride(null);
    vi.unstubAllGlobals();
  });

  it('mostra a imagem do Frigate no quadro do stream até o primeiro quadro em alta e então some', async () => {
    fetchMock.mockResolvedValue(new Response(new Blob(['jpg']), { status: 200 }));
    render(<Frame />);
    const preview = await screen.findByTestId('custom-camera-preview');
    expect(screen.getByTestId('video-area').contains(preview)).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/custom/camera/stream/1/preview.jpg');

    setNaturalWidth(screen.getByTestId('stream'), 2304);
    await waitFor(() => expect(screen.queryByTestId('custom-camera-preview')).toBeNull(), { timeout: 2000 });
  });

  it('não aparece quando a prévia não está configurada (404)', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 404 }));
    render(<Frame />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.queryByTestId('custom-camera-preview')).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('não aparece sem stream (modo snapshot) nem quando desligada', async () => {
    fetchMock.mockResolvedValue(new Response(new Blob(['jpg']), { status: 200 }));
    const { unmount } = render(<Frame withStream={false} />);
    await new Promise((r) => setTimeout(r, 300));
    expect(fetchMock).not.toHaveBeenCalled();
    unmount();
    setCameraPreviewOverride(false);
    render(<Frame />);
    await new Promise((r) => setTimeout(r, 300));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('some se o stream der erro (o aviso do upstream fica visível)', async () => {
    fetchMock.mockResolvedValue(new Response(new Blob(['jpg']), { status: 200 }));
    render(<Frame />);
    await screen.findByTestId('custom-camera-preview');
    screen.getByTestId('stream').dispatchEvent(new Event('error'));
    await waitFor(() => expect(screen.queryByTestId('custom-camera-preview')).toBeNull());
  });
});

describe('cameraAspect', () => {
  it('lê a rotação do transform e calcula a proporção exibida', async () => {
    const { rotationFromTransform, displayedAspect, fitRect } = await import('../camera/cameraAspect');
    expect(rotationFromTransform('scale(1) translate(0px, 0px) rotate(270deg)')).toBe(270);
    expect(rotationFromTransform('rotate(-90deg)')).toBe(270);
    expect(rotationFromTransform('')).toBe(0);
    expect(displayedAspect(2304, 1296, 270)).toBeCloseTo(1296 / 2304);
    expect(displayedAspect(2304, 1296, 0)).toBeCloseTo(2304 / 1296);
    expect(fitRect(390, 775, 1296 / 2304)).toEqual({ width: 390, height: 693 });
  });
});
