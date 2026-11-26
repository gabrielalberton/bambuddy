import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import type { Plan } from '../plotter/api';
import { loadSession, saveSession, SESSION_MAX_AGE_MS, type Session } from '../plotter/session';

const session = (over: Partial<Session> = {}): Session => ({
  at: 1_000_000, paper: { x: 23, y: 0, w: 210, h: 297, margin: 5, thickness: 0.1 },
  placement: { cx: 128, cy: 110, width: 150, rotation: 0 }, customized: true, activePen: 'padrao', kind: 'zsweep',
  pressure: 'variable', widthMode: 'fit', threshold: null, background: true, ink: 'luma', invert: 'auto',
  excluded: [2, 5], drawingId: 'abc', plan: { id: 'p1', ok: true } as unknown as Plan, ...over,
});

describe('rascunho do Plotter no navegador', () => {
  // O setup dos testes troca o localStorage por mocks vazios: aqui ele vira um armazenamento de verdade.
  const store = new Map<string, string>();
  beforeEach(() => {
    store.clear();
    vi.mocked(localStorage.setItem).mockClear();
    (localStorage.getItem as Mock).mockImplementation((name: string) => store.get(name) ?? null);
    (localStorage.setItem as Mock).mockImplementation((name: string, value: string) => { store.set(name, value); });
  });

  it('guarda e devolve papel, desenho, opções e plano validado, por impressora', () => {
    saveSession(1, session());
    expect(loadSession(1, 1_000_500)).toEqual(session());
    expect(loadSession(2, 1_000_500)).toBeNull();
  });

  it('descarta rascunho antigo ou corrompido', () => {
    saveSession(1, session());
    expect(loadSession(1, 1_000_000 + SESSION_MAX_AGE_MS + 1)).toBeNull();
    store.set('plotter-session-1', '{nao e json');
    expect(loadSession(1, 1_000_500)).toBeNull();
    store.set('plotter-session-1', JSON.stringify({ ...session(), paper: { x: 'a' } }));
    expect(loadSession(1, 1_000_500)).toBeNull();
  });

  it('rascunho com um dos testes antigos volta ao desenho e descarta o plano', () => {
    store.set('plotter-session-1', JSON.stringify(session({ kind: 'wave' as never })));
    expect(loadSession(1, 1_000_500)).toMatchObject({ kind: 'drawing', plan: null, drawingId: 'abc' });
  });

  it('sem espaço para o plano, guarda o resto do rascunho', () => {
    (localStorage.setItem as Mock).mockImplementationOnce(() => { throw new DOMException('cheio', 'QuotaExceededError'); });
    saveSession(1, session());
    expect(vi.mocked(localStorage.setItem)).toHaveBeenCalledTimes(2);
    expect(loadSession(1, 1_000_500)).toMatchObject({ kind: 'zsweep', drawingId: 'abc', plan: null });
  });
});
