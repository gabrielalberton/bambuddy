// Web Worker: reconstrói o objeto a partir dos registros de extrusão do G-code.
// Entrada : { xyz:Int16Array, t:Float32Array, kind:Uint8Array, attr:Uint16Array, attrs:[[feat,w,h,fil,layer]], features:[...], budget:{maxTris} }
// Saída   : atributos intercalados por tempo (position, normal Int8, aT, aF), índice, e índices de início/fim por "strand"
//           (trecho contínuo de extrusão) para limitar o draw range ao que já foi/falta imprimir.
// Perfil da linha: seção "bead" achatada (6 pontos) com largura/altura reais da camada (LINE_WIDTH, LAYER_HEIGHT).

const PROFILE6 = [[-0.5, 0.0, -1, 0], [-0.5, 0.5, -0.92, 0.38], [-0.3, 1.0, -0.38, 0.92], [0.3, 1.0, 0.38, 0.92], [0.5, 0.5, 0.92, 0.38], [0.5, 0.0, 1, 0]];
const PROFILE4 = [[-0.5, 0.0, -1, 0.1], [-0.34, 1.0, -0.6, 0.8], [0.34, 1.0, 0.6, 0.8], [0.5, 0.0, 1, 0.1]];
// recheio barato: só a face de cima do filete (2 triângulos por segmento); visto de cima/lado basta para ver o preenchimento
const PROFILE2 = [[-0.5, 1.0, 0, 1], [0.5, 1.0, 0, 1]];
const INFILL = new Set(['Sparse infill', 'Internal solid infill', 'Gap infill']);
const INNER = new Set(['Inner wall']);

export function build(m) {
  const { xyz, t, kind, attr, attrs, features } = m;
  const maxTris = m.budget?.maxTris ?? 2000000;
  const n = t.length;
  // 1) quais registros entram: extrusão, a partir da camada 1
  const featName = (a) => features[attrs[a][0]];
  const passes = [
    // o recheio é o ÚLTIMO a sair: antes, perfil mais simples (4 pontos) e simplificação mais grossa na peça inteira
    { name: 'full', drop: new Set(), prof: PROFILE6, tol: 0.05 },
    { name: 'recheio-plano', drop: new Set(), prof: PROFILE6, infillProf: PROFILE2, tol: 0.05 },
    { name: 'full-4', drop: new Set(), prof: PROFILE4, infillProf: PROFILE2, tol: 0.08 },
    { name: 'full-4-grosso', drop: new Set(), prof: PROFILE4, infillProf: PROFILE2, tol: 0.2 },
    { name: 'sem-recheio-esparso', drop: new Set(['Sparse infill']), prof: PROFILE4, infillProf: PROFILE2, tol: 0.2 },
    { name: 'sem-recheio-4', drop: INFILL, prof: PROFILE4, tol: 0.08 },
    { name: 'sem-recheio-parede-int', drop: new Set([...INFILL, ...INNER]), prof: PROFILE4, tol: 0.12 },
  ];
  let chosen = null, strands = null;
  for (const p of passes) {
    strands = collect(p, m, featName);
    const tris = strands.tris;
    if (tris <= maxTris || p === passes[passes.length - 1]) { chosen = p; break; }
  }
  return emit(strands, chosen, m);
}

// Percorre os registros e monta strands (listas de vértices x,y,z,t,w,h,fil) já simplificados (colinear + linear no tempo).
function collect(p, m, featName) {
  const { xyz, t, kind, attr, attrs } = m;
  const n = t.length;
  const out = [];
  let tris = 0;
  let cur = null;
  const flush = () => {
    if (cur && cur.pts.length >= 2) { tris += (cur.pts.length - 1) * 2 * (cur.prof.length - 1); out.push(cur); }
    cur = null;
  };
  for (let i = 0; i < n; i++) {
    const a = attrs[attr[i]];
    const layer = a[4];
    const feat = featName(attr[i]);
    if (kind[i] !== 1 || layer < 1 || p.drop.has(feat)) { flush(); continue; }
    const fil = a[3];
    const prof = p.infillProf && INFILL.has(feat) ? p.infillProf : p.prof;
    const x1 = xyz[i * 3] * 0.01, y1 = xyz[i * 3 + 1] * 0.01, z1 = xyz[i * 3 + 2] * 0.01;
    const px = i > 0 ? xyz[(i - 1) * 3] * 0.01 : x1, py = i > 0 ? xyz[(i - 1) * 3 + 1] * 0.01 : y1, pz = i > 0 ? xyz[(i - 1) * 3 + 2] * 0.01 : z1;
    const t0 = i > 0 ? t[i - 1] : 0;
    if (cur && (cur.fil !== fil || cur.layer !== layer || cur.prof !== prof)) flush();
    if (!cur) {
      cur = { fil, layer, prof, pts: [], i0: i };
      cur.pts.push({ x: px, y: py, z: pz, t: t0, w: a[1], h: a[2] });
    } else {
      const lp = cur.pts[cur.pts.length - 1];
      if (Math.abs(lp.x - px) > 0.02 || Math.abs(lp.y - py) > 0.02) {   // descontinuidade (salto): novo strand
        flush();
        cur = { fil, layer, prof, pts: [], i0: i };
        cur.pts.push({ x: px, y: py, z: pz, t: t0, w: a[1], h: a[2] });
      }
    }
    // Simplificação: tenta descartar o último ponto se ele é colinear com (anterior -> novo) e linear no tempo.
    const pts = cur.pts;
    const nw = { x: x1, y: y1, z: z1, t: t[i], w: a[1], h: a[2] };
    if (pts.length >= 2) {
      const A = pts[pts.length - 2], B = pts[pts.length - 1];
      if (collinear(A, B, nw, p.tol) && B.w === nw.w && Math.abs(B.z - A.z) < 1e-3 && Math.abs(nw.z - B.z) < 1e-3) {
        pts[pts.length - 1] = nw;   // substitui B por N (estende o segmento)
        continue;
      }
    }
    pts.push(nw);
  }
  flush();
  return { list: out, tris };
}

function collinear(A, B, N, tol) {
  const dx = N.x - A.x, dy = N.y - A.y;
  const L = Math.hypot(dx, dy);
  if (L < 1e-6) return false;
  // distância de B à reta A-N
  const d = Math.abs((B.x - A.x) * dy - (B.y - A.y) * dx) / L;
  if (d > tol) return false;
  // B tem de estar entre A e N e o tempo deve ser ~linear
  const s = ((B.x - A.x) * dx + (B.y - A.y) * dy) / (L * L);
  if (s < 0 || s > 1) return false;
  const tl = A.t + (N.t - A.t) * s;
  return Math.abs(B.t - tl) < 0.03;
}

function emit(strands, p, m) {
  const list = strands.list;
  let nv = 0, nt = 0;
  for (const s of list) { const NP = s.prof.length; nv += s.pts.length * NP; nt += (s.pts.length - 1) * 2 * (NP - 1); }
  const pos = new Float32Array(nv * 3);
  const nor = new Int8Array(nv * 3);
  const aT = new Float32Array(nv);
  const aF = new Uint8Array(nv);
  const idx = new Uint32Array(nt * 3);
  const sIdx = new Uint32Array(list.length + 1);   // início (em triângulos*3) de cada strand
  const sT0 = new Float32Array(list.length);
  const sT1 = new Float32Array(list.length);
  let vo = 0, io = 0;
  let zmax = 0, bx0 = 1e9, bx1 = -1e9, by0 = 1e9, by1 = -1e9;
  for (let si = 0; si < list.length; si++) {
    const s = list[si];
    const pts = s.pts;
    const prof = s.prof, NP = prof.length;   // perfil por strand (recheio pode ser plano)
    sIdx[si] = io;
    sT0[si] = pts[0].t; sT1[si] = pts[pts.length - 1].t;
    const base = vo;
    for (let k = 0; k < pts.length; k++) {
      const P = pts[k];
      // direções de entrada/saída (plano XY)
      let ix = 0, iy = 0, ox = 0, oy = 0;
      if (k > 0) { ix = P.x - pts[k - 1].x; iy = P.y - pts[k - 1].y; const l = Math.hypot(ix, iy) || 1; ix /= l; iy /= l; }
      if (k < pts.length - 1) { ox = pts[k + 1].x - P.x; oy = pts[k + 1].y - P.y; const l = Math.hypot(ox, oy) || 1; ox /= l; oy /= l; }
      if (k === 0) { ix = ox; iy = oy; }
      if (k === pts.length - 1) { ox = ix; oy = iy; }
      let dx = ix + ox, dy = iy + oy;
      let dl = Math.hypot(dx, dy);
      if (dl < 1e-4) { dx = ox; dy = oy; dl = 1; }
      dx /= dl; dy /= dl;
      // normal à esquerda (no plano) e fator de mitra
      const nx = -dy, ny = dx;
      const cosh = Math.max(0.55, nx * (-oy) + ny * ox);   // cos do meio-ângulo entre a normal do mitra e a do segmento de saída
      const miter = 1 / cosh;
      const w = P.w * Math.min(miter, 1.8), h = P.h;
      // ponto do bico: (x, y, z); a linha ocupa z-h .. z; coordenadas locais da mesa: (x-128, z, -y)
      for (let j = 0; j < NP; j++) {
        const pr = prof[j];
        const u = pr[0] * w, v = pr[1] * h;
        const X = P.x + nx * u, Y = P.y + ny * u, Z = P.z - h + v;
        const o = vo * 3;
        pos[o] = X; pos[o + 1] = Z; pos[o + 2] = -Y;
        // normal: componente lateral (pr[2]) ao longo de (nx,ny) + vertical (pr[3])
        const nl = Math.hypot(pr[2], pr[3]) || 1;
        const lat = pr[2] / nl, up = pr[3] / nl;
        nor[o] = Math.round((nx * lat) * 127); nor[o + 1] = Math.round(up * 127); nor[o + 2] = Math.round(-(ny * lat) * 127);
        aT[vo] = P.t;
        aF[vo] = s.fil;
        vo++;
      }
      if (P.z > zmax) zmax = P.z;
      if (P.x < bx0) bx0 = P.x; if (P.x > bx1) bx1 = P.x; if (P.y < by0) by0 = P.y; if (P.y > by1) by1 = P.y;
    }
    for (let k = 0; k < pts.length - 1; k++) {
      const r0 = base + k * NP, r1 = base + (k + 1) * NP;
      for (let j = 0; j < NP - 1; j++) {
        const a = r0 + j, b = r0 + j + 1, c = r1 + j, d = r1 + j + 1;
        idx[io++] = a; idx[io++] = c; idx[io++] = b;
        idx[io++] = b; idx[io++] = c; idx[io++] = d;
      }
    }
  }
  sIdx[list.length] = io;
  const out = { pos, nor, aT, aF, idx, sIdx, sT0, sT1, nStrands: list.length, tris: nt, verts: nv, lod: p.name, zmax, bbox: [bx0, by0, bx1, by1] };
  return { ok: true, ...out };
}
function Z0(P) { return P.z; }
