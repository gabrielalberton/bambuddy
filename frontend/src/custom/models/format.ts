/** Formatação curta para o celular (estilo Bambu Handy: 3.7k, 9.7 h, 2025-07-02). */

export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '';
  if (Math.abs(value) < 1000) return String(Math.round(value));
  const units: [number, string][] = [[1e9, 'B'], [1e6, 'M'], [1e3, 'k']];
  for (const [size, suffix] of units) {
    if (Math.abs(value) >= size) {
      const n = value / size;
      return `${n >= 100 ? Math.round(n) : Number(n.toFixed(1))}${suffix}`;
    }
  }
  return String(value);
}

/** Data ISO da API → AAAA-MM-DD (o que o Handy mostra); string inválida → ''. */
export function isoDate(value: string | null | undefined): string {
  if (!value) return '';
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return match ? match[1] : '';
}

export function duration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  return `${Number((seconds / 3600).toFixed(1))} h`;
}

export function grams(value: number): string {
  return value >= 1000 ? `${Number((value / 1000).toFixed(2))} kg` : `${Math.round(value)} g`;
}
