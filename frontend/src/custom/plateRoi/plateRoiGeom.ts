/**
 * Geometria da área de detecção da mesa em quadrilátero (custom/CUSTOMIZATIONS.md, "Área da mesa em quadrilátero").
 * Pontos em frações 0-1 da imagem, ordem: sup. esq., sup. dir., inf. dir., inf. esq.
 */
export type Point = [number, number];
export type Quad = [Point, Point, Point, Point];
export interface QuadRoi { x: number; y: number; w: number; h: number; points?: Point[] }

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const round4 = (v: number) => Math.round(v * 10000) / 10000;

export function rectToQuad(r: { x: number; y: number; w: number; h: number }): Quad {
  return [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]];
}

/** Os cantos da área; uma área antiga só com o retângulo vira os 4 cantos dele. */
export function roiToQuad(roi: QuadRoi): Quad {
  const p = roi.points;
  if (p && p.length === 4) return p.map(([x, y]) => [x, y]) as Quad;
  return rectToQuad(roi);
}

/** Payload para o backend: cantos + o retângulo envolvente (as colunas do upstream). */
export function quadToRoi(quad: Quad): QuadRoi {
  const pts = quad.map(([x, y]) => [round4(clamp01(x)), round4(clamp01(y))] as Point);
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, w: round4(Math.max(...xs) - x), h: round4(Math.max(...ys) - y), points: pts };
}

export function moveCorner(quad: Quad, index: number, to: Point): Quad {
  const next = quad.map((p) => [...p]) as Quad;
  next[index] = [clamp01(to[0]), clamp01(to[1])];
  return next;
}

/** Desloca a área inteira sem deixar nenhum canto sair da imagem. */
export function moveQuad(quad: Quad, dx: number, dy: number): Quad {
  const xs = quad.map((p) => p[0]);
  const ys = quad.map((p) => p[1]);
  const cdx = Math.min(1 - Math.max(...xs), Math.max(-Math.min(...xs), dx));
  const cdy = Math.min(1 - Math.max(...ys), Math.max(-Math.min(...ys), dy));
  return quad.map(([x, y]) => [x + cdx, y + cdy]) as Quad;
}

/** Ponto dentro do polígono (ray casting); usado só para decidir se o toque arrasta a área. */
export function pointInQuad(quad: Quad, [px, py]: Point): boolean {
  let inside = false;
  for (let i = 0, j = quad.length - 1; i < quad.length; j = i++) {
    const [xi, yi] = quad[i];
    const [xj, yj] = quad[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

let quadOverride: boolean | null = null;

/** Só para testes: força o editor (null volta ao padrão). */
export function setPlateRoiQuadOverride(on: boolean | null): void {
  quadOverride = on;
}

/**
 * Interruptor: localStorage['custom.plateRoiQuad'] = 'off' volta aos sliders do upstream.
 * Nos testes (vitest) o efetivo é desligado, para a suíte do upstream seguir igual.
 */
export function plateRoiQuadEnabled(): boolean {
  if (quadOverride !== null) return quadOverride;
  if (import.meta.env.MODE === 'test') return false;
  try {
    return localStorage.getItem('custom.plateRoiQuad') !== 'off';
  } catch {
    return true;
  }
}
