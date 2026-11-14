// Web Worker (módulo): reconstrói o objeto a partir dos registros de extrusão. Lógica em geom-build.js (testável em Node).
import { build } from './geom-build.js';

self.onmessage = (ev) => {
  const m = ev.data;
  try {
    const r = build(m);
    self.postMessage(r, [r.pos.buffer, r.nor.buffer, r.aT.buffer, r.aF.buffer, r.idx.buffer, r.sIdx.buffer, r.sT0.buffer, r.sT1.buffer]);
  } catch (e) { self.postMessage({ error: String((e && e.stack) || e) }); }
};

