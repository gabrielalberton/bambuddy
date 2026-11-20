import { describe, it, expect } from 'vitest';
// @ts-expect-error módulo JS puro do motor do twin
import { build } from '../twin/engine/geom-build.js';

// parede (100 registros) + recheio esparso (100 registros) numa camada, em zigue-zague (nada colinear)
function job() {
  const features = ['Outer wall', 'Sparse infill'];
  const attrs = [[0, 0.45, 0.2, 0, 1], [1, 0.45, 0.2, 0, 1]];
  const N = 200;
  const xyz = new Int16Array(N * 3), t = new Float32Array(N), kind = new Uint8Array(N).fill(1), attr = new Uint16Array(N);
  for (let i = 0; i < N; i++) {
    xyz[i * 3] = (i % 2 ? 100 : 0) * 100 + i * 10; xyz[i * 3 + 1] = i * 50; xyz[i * 3 + 2] = 20;
    t[i] = i; attr[i] = i < 100 ? 0 : 1;
  }
  return { xyz, t, kind, attr, attrs, features };
}

describe('twin: o recheio só sai da geometria em último caso', () => {
  it('sem limite: tudo com perfil completo', () => {
    const r = build({ ...job(), budget: { maxTris: 1e9 } });
    expect(r.lod).toBe('full');
  });
  it('limite apertado: simplifica o perfil (recheio plano) e mantém o recheio', () => {
    const r = build({ ...job(), budget: { maxTris: 1000 } });
    expect(r.lod).toBe('full-4');
    expect(r.nStrands).toBe(2);
    expect(r.idx.length / 3).toBe(r.tris);
    expect(r.sT1[1]).toBeGreaterThan(150); // o strand do recheio (t 100..199) está lá
  });
});
