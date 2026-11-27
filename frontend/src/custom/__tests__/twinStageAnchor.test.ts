import { describe, expect, it } from 'vitest';
import { Tracker } from '../twin/engine/sync.js';

// Programa mínimo: só o que o Tracker lê para a rotina de início (claims por estágio, sem M73/camadas/esperas).
const program = (claims: Array<[number, number]>) => ({
  m73: [], layers: [], holds: [], swaps: [], total: 500,
  claims: claims.map(([n, t]) => ({ line: 0, t, n })),
  holdAt: () => null, lineToT: () => 0, posAt: () => undefined,
});

const feed = (tr: Tracker, stg: number, now: number) =>
  tr.feed({ gcode_state: 'RUNNING', stg_cur: stg, spd_mag: 100 }, now, 0);

describe('Twin: reancoragem por estágio da A1', () => {
  it('ao mudar stg_cur, puxa o relógio para o claim do estágio (simulado e real têm durações diferentes)', () => {
    const tr = new Tracker(program([[2, 0.5], [13, 4], [24, 60], [4, 61], [8, 165], [3, 250]]) as never);
    tr.locked = true; tr.mode = 'running'; tr.scale = 1; tr.T = 20; tr.tLast = 0;
    feed(tr, 13, 1);                       // primeira leitura só registra o estágio
    feed(tr, 24, 40);                      // homing real acabou antes do simulado (T≈20 contra claim 60)
    expect(tr.T + tr.corr).toBeGreaterThan(55);
    expect(tr.diag.stage).toBe(1);
    feed(tr, 8, 120);                      // etapa 8 ainda mais adiante
    expect(tr.diag.stage).toBe(2);
    expect(tr.T + tr.corr).toBeGreaterThan(160);
  });

  it('não ancora no mesmo estágio nem em estágio desconhecido', () => {
    const tr = new Tracker(program([[13, 4], [24, 60]]) as never);
    tr.locked = true; tr.mode = 'running'; tr.scale = 1; tr.T = 10; tr.tLast = 0;
    feed(tr, 13, 1); feed(tr, 13, 2); feed(tr, 77, 3);
    expect(tr.diag.stage ?? 0).toBe(0);
  });
});
