// Decodifica o pacote binário do job (ver twin/server/twin_server/pack.py) e responde "onde está o cabeçote no tempo T?".
const pad4 = (n) => (n + 3) & ~3;

export function decodeJob(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'A1TW') throw new Error('pacote inválido');
  const hl = dv.getUint32(8, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 12, hl)));
  const n = header.n;
  let off = 12 + hl;
  const xyz = new Int16Array(buf, off, n * 3); off += pad4(n * 6);
  const t = new Float32Array(buf, off, n); off += n * 4;
  const line = new Uint32Array(buf, off, n); off += n * 4;
  const kind = new Uint8Array(buf, off, n); off += pad4(n);
  const attr = new Uint16Array(buf, off, n);
  return new Program(header, { xyz, t, line, kind, attr });
}

export class Program {
  constructor(header, a) {
    this.h = header;
    this.n = header.n;
    this.xyz = a.xyz; this.t = a.t; this.line = a.line; this.kind = a.kind; this.attr = a.attr;
    this.total = header.total_time;
    const ev = header.events;
    this.m73 = ev.m73.map(([line, t, p, r]) => ({ line, t, p, r }));
    this.layers = ev.layer.map(([line, t, n]) => ({ line, t, n }));
    this.claims = ev.claim.map(([line, t, n]) => ({ line, t, n }));
    this.swaps = (ev.swap || []).map(([line, t, n, c]) => ({ line, t, n, c }));
    this.tools = ev.tool.map(([line, t, n]) => ({ line, t, n }));
    this.holds = ev.hold.map(([line, t0, t1, s, a, dir]) => ({ line, t0, t1, s, a, dir }));
    this.layerStart = ev.layer_start.map(([line, t, n, z]) => ({ line, t, n, z }));
    this.colors = header.colors;
    this.attrs = header.attrs;
    this.features = header.features;
    this.meta = header.meta;
    this.holdT0 = this.holds.map((h) => h.t0);
  }

  // menor i com t[i] >= T
  idx(T) {
    const t = this.t;
    let lo = 0, hi = this.n - 1;
    if (T > t[hi]) return hi;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (t[mid] >= T) hi = mid; else lo = mid + 1;
    }
    return lo;
  }

  // posição (mm) do bico no tempo T; devolve também o índice do registro e se está extrudando
  posAt(T, out) {
    const i = this.idx(T);
    const xyz = this.xyz;
    const t1 = this.t[i];
    const t0 = i > 0 ? this.t[i - 1] : 0;
    const ax = i > 0 ? xyz[(i - 1) * 3] : xyz[0], ay = i > 0 ? xyz[(i - 1) * 3 + 1] : xyz[1], az = i > 0 ? xyz[(i - 1) * 3 + 2] : xyz[2];
    const f = t1 <= t0 ? 1 : Math.min(1, Math.max(0, (T - t0) / (t1 - t0)));
    out.x = (ax + (xyz[i * 3] - ax) * f) * 0.01;
    out.y = (ay + (xyz[i * 3 + 1] - ay) * f) * 0.01;
    out.z = (az + (xyz[i * 3 + 2] - az) * f) * 0.01;
    out.rec = i;
    out.kind = this.kind[i];
    out.f = f;
    return out;
  }

  // tempo de programa em que a linha `L` do G-code começa a ser executada
  lineToT(L) {
    const line = this.line;
    let lo = 0, hi = this.n - 1;
    if (L > line[hi]) return this.t[hi];
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (line[mid] >= L) hi = mid; else lo = mid + 1;
    }
    return lo > 0 ? this.t[lo - 1] : 0;
  }

  holdAt(T) {
    const a = this.holdT0;
    let lo = 0, hi = a.length - 1, k = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (a[mid] <= T) { k = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return k >= 0 && T < this.holds[k].t1 ? this.holds[k] : null;
  }

  // índice do último evento de `arr` (ordenado por t) com t <= T
  lastBefore(arr, T) {
    let lo = 0, hi = arr.length - 1, k = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid].t <= T) { k = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return k;
  }
}
