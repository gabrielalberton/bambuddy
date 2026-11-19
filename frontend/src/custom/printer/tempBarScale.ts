/**
 * Barra de temperatura do bico e da mesa no card da impressora (custom(temp-bars)).
 *
 * Mesmo desenho da barrinha de nível de filamento (trilho `h-1.5 bg-black/30
 * rounded-full`, preenchimento de cor sólida), embaixo do número que o upstream
 * já mostra (o número não muda). Escala, limiar de "frio" e cor:
 *  - mesa: 20 °C → 0%, 67 °C → 100%; abaixo de 30 °C a barra fica com opacidade 0,6;
 *  - bico: 25 °C → 0%, 250 °C → 100%; abaixo de 40 °C, opacidade 0,6;
 *  - fora da faixa, clamp em 0/100%;
 *  - cor: de azul claro (#7cc4ff) a vermelho vivo (#ff1a1a) pela fração, interpolada
 *    em HSL pelo violeta/magenta (ver tempBarColor); a barra inteira usa a cor da
 *    posição atual (como a de filamento, que é de cor única), porque numa barra de
 *    ~100 px no celular um gradiente deixa a ponta pequena demais para ler
 *    "quente/frio" de relance.
 *  - se o alvo for > 0, um tracinho branco marca o alvo no trilho.
 * Bico duplo (nozzle_2) não ganha barra: o cartão do upstream mostra "L / R".
 *
 * Funções puras aqui; o componente em TempBar.tsx.
 */
export type TempBarKind = 'nozzle' | 'bed';

export const TEMP_BAR_SCALE: Record<TempBarKind, { min: number; max: number; cold: number }> = {
  bed: { min: 20, max: 67, cold: 30 },
  nozzle: { min: 25, max: 250, cold: 40 },
};

export const TEMP_BAR_COLD = '#7cc4ff';
export const TEMP_BAR_HOT = '#ff1a1a';
export const TEMP_BAR_COLD_OPACITY = 0.6;

/** Fração 0..1 da temperatura na escala do aquecedor (clamp; inválido = 0). */
export function tempFraction(kind: TempBarKind, temp: number | null | undefined): number {
  const { min, max } = TEMP_BAR_SCALE[kind];
  if (typeof temp !== 'number' || !Number.isFinite(temp)) return 0;
  return Math.min(1, Math.max(0, (temp - min) / (max - min)));
}

/** Opacidade da barra: 0,6 abaixo do limiar de "frio" do aquecedor, senão 1. */
export function tempBarOpacity(kind: TempBarKind, temp: number | null | undefined): number {
  if (typeof temp !== 'number' || !Number.isFinite(temp)) return TEMP_BAR_COLD_OPACITY;
  return temp < TEMP_BAR_SCALE[kind].cold ? TEMP_BAR_COLD_OPACITY : 1;
}

function hexToHsl(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}

function hslToHex(h: number, s: number, l: number): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return `#${[r, g, b].map((v) => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('')}`;
}

/**
 * Cor da fração (0 = azul claro, 1 = vermelho vivo), em `#rrggbb`.
 * Interpola em HSL (matiz 207° → 360°, passando por violeta e magenta), não em
 * RGB: em RGB o meio da escala vira um lilás acinzentado que parece "desligado".
 */
export function tempBarColor(fraction: number): string {
  const f = Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0));
  if (f === 0) return TEMP_BAR_COLD;
  if (f === 1) return TEMP_BAR_HOT;
  const [h0, s0, l0] = hexToHsl(TEMP_BAR_COLD);
  const [h1raw, s1, l1] = hexToHsl(TEMP_BAR_HOT);
  const h1 = h1raw < h0 ? h1raw + 360 : h1raw;
  return hslToHex((h0 + (h1 - h0) * f) % 360, s0 + (s1 - s0) * f, l0 + (l1 - l0) * f);
}
