import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { Pen } from '../plotter/api';
import { Plate } from '../plotter/Plate';

it('paints the calibrated plate, A4 paper and reachable area on mount', () => {
  const context = {
    setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), strokeRect: vi.fn(),
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
    setLineDash: vi.fn(), arc: vi.fn(), fill: vi.fn(), fillText: vi.fn(),
    save: vi.fn(), restore: vi.fn(), translate: vi.fn(), scale: vi.fn(), clip: vi.fn(),
  };
  const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
    .mockReturnValue(context as unknown as ReturnType<HTMLCanvasElement['getContext']>);
  vi.stubGlobal('Path2D', class {
    moveTo = vi.fn();
    lineTo = vi.fn();
    quadraticCurveTo = vi.fn();
    closePath = vi.fn();
  });
  try {
    render(<Plate
      machine={{ plate_w: 256, plate_h: 256, nozzle_x: [0, 256], nozzle_y: [0, 254] }}
      paper={{ x: 23, y: 0, w: 210, h: 297, margin: 5, thickness: 0.1 }}
      area={[28, 5, 228, 222]} pen={{ depth_max: 1.2 } as Pen}
      drawing={null} placement={{ cx: 128, cy: 110, width: 150, rotation: 0 }}
      layer="vector" edit="paper" time={0} travel={false} locked={false} excluded={new Set()}
      onPaper={vi.fn()} onPlacement={vi.fn()} onToggleStroke={vi.fn()}
    />);
    expect(getContext.mock.contexts).toContain(screen.getByLabelText(/Vista superior da mesa/));
    expect(context.translate).toHaveBeenCalledWith(128, -128);
    expect(context.clip).toHaveBeenCalledWith(expect.any(Path2D), 'evenodd');
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 2000, 2000);
    expect(context.fillRect).toHaveBeenCalledWith(23, -297, 210, 297);
    expect(context.strokeRect).toHaveBeenCalledWith(28, -222, 200, 217);
  } finally {
    getContext.mockRestore();
    vi.unstubAllGlobals();
  }
});

it('paints the aerial photo with its dimmed margin and a see-through paper', async () => {
  const context = {
    setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), strokeRect: vi.fn(),
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), drawImage: vi.fn(),
    setLineDash: vi.fn(), arc: vi.fn(), fill: vi.fn(), fillText: vi.fn(),
    save: vi.fn(), restore: vi.fn(), translate: vi.fn(), scale: vi.fn(), clip: vi.fn(),
    globalAlpha: 1,
  };
  const alphaAtPaper: number[] = [];
  context.fillRect.mockImplementation((x: number) => { if (x === 23) alphaAtPaper.push(context.globalAlpha); });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
    .mockReturnValue(context as unknown as ReturnType<HTMLCanvasElement['getContext']>);
  vi.stubGlobal('Path2D', class { moveTo = vi.fn(); lineTo = vi.fn(); quadraticCurveTo = vi.fn(); closePath = vi.fn(); });
  vi.stubGlobal('Image', class {
    onload: (() => void) | null = null;
    set src(_: string) { queueMicrotask(() => this.onload?.()); }
  });
  try {
    render(<Plate
      machine={{ plate_w: 256, plate_h: 256, nozzle_x: [0, 256], nozzle_y: [0, 254] }}
      paper={{ x: 23, y: 0, w: 210, h: 297, margin: 5, thickness: 0.1 }}
      area={null} pen={{ depth_max: 1.2 } as Pen} aerial={{ src: 'data:image/jpeg;base64,AA==', margin: 30 }}
      drawing={null} placement={{ cx: 128, cy: 110, width: 150, rotation: 0 }}
      layer="vector" edit="paper" time={0} travel={false} locked={false} excluded={new Set()}
      onPaper={vi.fn()} onPlacement={vi.fn()} onToggleStroke={vi.fn()}
    />);
    await vi.waitFor(() => expect(context.drawImage).toHaveBeenCalledWith(expect.anything(), -30, -286, 316, 316));
    expect(alphaAtPaper.at(-1)).toBeLessThan(1);
  } finally {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  }
});
