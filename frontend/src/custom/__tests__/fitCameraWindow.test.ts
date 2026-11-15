import { describe, expect, it } from 'vitest';
import { fitWindow } from '../camera/useFitCameraWindow';

const vp = { width: 390, height: 844 };

describe('fitWindow', () => {
  it('janela vertical: largura mínima, altura cresce para não sobrar preto', () => {
    const r = fitWindow({ x: 0, y: 64, width: 204, height: 320 }, 9 / 16, vp);
    expect(r.width).toBe(200);
    expect(r.height).toBe(Math.round(198 / (9 / 16) + 42));
  });
  it('largura segue a altura quando cabe', () => {
    const r = fitWindow({ x: 0, y: 64, width: 380, height: 500 }, 9 / 16, vp);
    expect(r.height).toBe(500);
    expect(r.width).toBe(Math.round(458 * (9 / 16) + 2));
  });
  it('não passa da tela', () => {
    const r = fitWindow({ x: 10, y: 64, width: 380, height: 300 }, 16 / 9, vp);
    expect(r.width).toBeLessThanOrEqual(370);
    expect(r.x).toBe(10);
  });
});
