import type { Kind, Paper, Placement, Plan } from './api';
import type { SweepVariant } from './thickness';

/**
 * Rascunho do que está montado na tela do Plotter (papel, desenho, opções e plano validado), guardado no
 * navegador para sobreviver a recarregar a página ou ao navegador descartar a aba. Fica só neste aparelho;
 * as calibrações da caneta continuam no servidor e nunca entram aqui.
 */
export type Session = {
  at: number; paper: Paper; placement: Placement; customized: boolean; activePen: string; kind: Kind; variant?: SweepVariant;
  pressure: string; widthMode: string; threshold: number | null; background: boolean; ink: string; invert: string;
  excluded: number[]; drawingId: string | null; plan: Plan | null;
};

const KINDS: string[] = ['drawing', 'zsweep', 'cross', 'frame'];
export const SESSION_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const key = (id: number) => `plotter-session-${id}`;

const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value);
const isPaper = (p: Record<string, unknown> | undefined) => !!p && ['x', 'y', 'w', 'h', 'margin', 'thickness'].every(k => finite(p[k]));
const isPlacement = (p: Record<string, unknown> | undefined) => !!p && ['cx', 'cy', 'width', 'rotation'].every(k => finite(p[k]));

export function loadSession(id: number, now = Date.now()): Session | null {
  try {
    const raw = localStorage.getItem(key(id));
    if (!raw) return null;
    const data = JSON.parse(raw) as Partial<Session>;
    if (!finite(data.at) || now - (data.at as number) > SESSION_MAX_AGE_MS) return null;
    if (!isPaper(data.paper as Record<string, unknown>) || !isPlacement(data.placement as Record<string, unknown>)) return null;
    if (typeof data.activePen !== 'string' || typeof data.kind !== 'string') return null;
    const known = KINDS.includes(data.kind as string);  // rascunho de antes da troca dos testes: volta ao desenho
    return {
      ...(data as Session),
      kind: known ? (data.kind as Kind) : 'drawing',
      variant: data.variant === 'speeds' || data.variant === 'reverse' ? data.variant : 'reference',
      excluded: Array.isArray(data.excluded) ? data.excluded.filter(finite) : [],
      drawingId: typeof data.drawingId === 'string' ? data.drawingId : null,
      plan: known && data.plan && typeof data.plan === 'object' ? data.plan : null,
    };
  } catch { return null; }
}

export function saveSession(id: number, session: Session) {
  try {
    localStorage.setItem(key(id), JSON.stringify(session));
  } catch {
    // Plano grande demais para o espaço do navegador: guarda o resto sem ele.
    try { localStorage.setItem(key(id), JSON.stringify({ ...session, plan: null })); } catch { /* sem armazenamento */ }
  }
}
