import { describe, expect, it } from 'vitest';
import { poseTimeShift, VisionMotion } from '../twin/engine/vision.js';

type Position = { x?: number; y?: number; z?: number };
const continuous = (t: number, out: Position) => {
  Object.assign(out, { x: 20 + 30 * t, y: 120 + 20 * Math.sin(t), z: 10 });
};

describe('observações de câmera no Twin', () => {
  it('acha o deslocamento pelos eixos vistos e recusa uma trajetória periódica ambígua', () => {
    const stamps = [2, 2.2, 2.4, 2.6, 2.8, 3.0];
    const samples = stamps.map((programTime) => {
      const pose = {};
      continuous(programTime + 0.36, pose);
      return { programTime, pose };
    });
    expect(poseTimeShift({ total: 20, posAt: continuous }, samples)).toBeCloseTo(0.36, 2);
    const repeated = (t: number, p: Position) => Object.assign(p, { x: 100 + 30 * Math.sin(2 * Math.PI * t) });
    const ambiguous = stamps.map((programTime) => ({ programTime, pose: repeated(programTime, {}) }));
    expect(poseTimeShift({ total: 20, posAt: repeated }, ambiguous)).toBeNull();
  });

  it('devolve só os eixos do quadro atual e expira pela hora da captura', () => {
    const camera = new VisionMotion();
    camera.observe({ ts: 1001, vision: { at: 1000.7, x: 20, z: 45 } }, 9, null);
    expect(camera.current(9.2)).toEqual({ x: 20, z: 45 });
    camera.observe({ ts: 1001.1, vision: { at: 1000.9, y: 27 } }, 9.1, null);
    expect(camera.current(9.2)).toEqual({ y: 27 });
    expect(camera.current(11.5)).toBeNull();
    camera.observe({ ts: 1002.15, vision: { at: 1000.95, x: 120 } }, 10, null);
    expect(camera.current(10)).toEqual({ x: 120 });
    camera.observe({ ts: 1004.6, vision: { at: 1002, x: 121 } }, 12.6, null);
    expect(camera.current(12.6)).toBeNull();
    expect(camera.current(10)).toEqual({ x: 120 });
  });
});
