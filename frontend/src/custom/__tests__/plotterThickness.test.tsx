import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { HistoryItem, Pen, PenTypeInfo, Settings, TestLayouts } from '../plotter/api';
import { DrawingHistory } from '../plotter/History';
import { FALLBACK_MOUNTS, selectMount } from '../plotter/mounts';
import { ThicknessTests } from '../plotter/Thickness';
import { applyPenType, combResult, ladderResult, waveResult, wedgeResult } from '../plotter/thickness';

const [, RIGID] = FALLBACK_MOUNTS;

const BIC: PenTypeInfo = {
  key: 'bic', name: 'Caneta BIC', about: 'Esferográfica.',
  defaults: {
    spring: { name: 'Caneta BIC com mola', depth_min: 0.4, depth_max: 1.5, max_compression: 3, line_width: 0.4, draw_speed: 25 },
    rigid: { name: 'Caneta BIC sem mola', depth_min: 0.05, depth_max: 0.2, max_compression: 0.3, line_width: 0.4, draw_speed: 25 },
  },
};
const CANETINHA: PenTypeInfo = {
  key: 'canetinha', name: 'Canetinha', about: 'Feltro.',
  defaults: {
    spring: { name: 'Canetinha com mola', depth_min: 0.1, depth_max: 0.8, max_compression: 2, line_width: 1, draw_speed: 30 },
    rigid: { name: 'Canetinha sem mola', depth_min: 0.03, depth_max: 0.3, max_compression: 0.5, line_width: 1, draw_speed: 30 },
  },
};
const TYPES = [BIC, CANETINHA];
const LAYOUTS: TestLayouts = {
  ladder: { depths: [0, 0.1, 0.2, 0.35, 0.75, 1, 1.25, 1.5] },
  comb: { depths: [0.4, 0.77, 1.13, 1.5], spacings: [0.2, 0.25, 0.35, 0.45, 0.55, 0.7, 0.95, 1.2] },
  wedge: { from: 0, to: 1.5, length: 100 },
  wave: { from: 0.4, to: 1.5, length: 150, ramps: [5, 10, 20, 40] },
};

function pen(over: Partial<Pen> = {}): Pen {
  return {
    name: 'Caneta BIC com mola', mount: 'spring', pen_type: 'bic', offset_x: 0, offset_y: -32, z_contact: 4.2, lift: 3,
    depth_min: 0.4, depth_max: 1.5, max_compression: 3, line_width: 0.4, draw_speed: 25, travel_speed: 100,
    z_speed: 10, dwell_ms: 0, use_mesh: true, table: [], ...over,
  };
}

function settings(pens: Record<string, Pen>, active = 'padrao'): Settings {
  return {
    machine: { plate_w: 256, plate_h: 256, nozzle_x: [0, 256], nozzle_y: [0, 254] },
    pens, active_pen: active, paper: { x: 23, y: 0, w: 210, h: 297, margin: 5, thickness: 0.1 }, placement: null,
  };
}

const item = (id: string, name: string): HistoryItem => ({
  id, name, created_at: 1_795_000_000, updated_at: 1_795_000_000, strokes: 1234, width: 900, height: 500,
  options: {}, thumb: 'data:image/jpeg;base64,AAAA', can_revectorize: true,
});

describe('histórico de envios', () => {
  it('lista as imagens, marca a aberta, reabre e exclui', () => {
    const onOpen = vi.fn();
    const onDelete = vi.fn();
    render(<DrawingHistory items={[item('aaaaaaaaaaaa', 'logo'), item('bbbbbbbbbbbb', 'gato')]} current="bbbbbbbbbbbb"
      keep={30} canDelete onOpen={onOpen} onDelete={onDelete} />);
    expect(screen.getByText('de até 30', { exact: false })).toBeTruthy();
    const list = screen.getByRole('list', { name: 'Histórico de imagens' });
    expect(within(list).getAllByRole('listitem')[1].getAttribute('aria-current')).toBe('true');
    expect(screen.getAllByText(/1\.234 traços/)).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Abrir logo' }));
    expect(onOpen.mock.calls[0][0].id).toBe('aaaaaaaaaaaa');
    fireEvent.click(screen.getByRole('button', { name: 'Excluir gato' }));
    expect(onDelete.mock.calls[0][0].name).toBe('gato');
  });

  it('sem permissão de arquivos não oferece excluir; vazio não mostra nada', () => {
    const { container, rerender } = render(<DrawingHistory items={[]} canDelete onOpen={vi.fn()} onDelete={vi.fn()} />);
    expect(container.textContent).toBe('');
    rerender(<DrawingHistory items={[item('aaaaaaaaaaaa', 'logo')]} canDelete={false} onOpen={vi.fn()} onDelete={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Excluir/ })).toBeNull();
  });
});

describe('tipo de caneta', () => {
  it('trocar o tipo aplica os valores iniciais, zera contato e medidas e acompanha o nome padrão', () => {
    const next = applyPenType(pen({ table: [[0.4, 0.3], [1.5, 0.5]] }), CANETINHA, BIC, 'spring');
    expect(next).toMatchObject({ pen_type: 'canetinha', name: 'Canetinha com mola', depth_max: 0.8, line_width: 1, z_contact: null, table: [] });
    expect(applyPenType(pen({ name: 'Minha azul' }), CANETINHA, BIC, 'spring').name).toBe('Minha azul');
  });

  it('perfil novo de outro modo herda o tipo de caneta com os valores daquele modo', () => {
    const next = selectMount(settings({ padrao: pen() }), RIGID, TYPES);
    expect(next.pens[next.active_pen]).toMatchObject({ mount: 'rigid', pen_type: 'bic', max_compression: 0.3, depth_max: 0.2 });
  });
});

describe('resultados dos testes de espessura', () => {
  it('escada: linhas que marcaram viram a curva, a largura nunca diminui e a faixa segue o escolhido', () => {
    const depths = [0, 0.35, 0.75, 1, 1.5];
    const result = ladderResult(pen(), depths, [null, 0.3, 0.42, 0.4, 0.55], 1);
    if ('error' in result) throw new Error(result.error);
    expect(result.pen.table).toEqual([[0.35, 0.3], [0.75, 0.42], [1, 0.42], [1.5, 0.55]]);
    expect(result.pen).toMatchObject({ depth_min: 0.35, depth_max: 1, line_width: 0.3 });
    expect(result.notes.join(' ')).toMatch(/igualadas/);
    expect('error' in ladderResult(pen(), depths, [null, 0.3, null, null, null], null)).toBe(true);
  });

  it('pente: a largura fica entre a última célula fechada e a seguinte', () => {
    const spacings = [0.2, 0.3, 0.4, 0.6];
    const result = combResult(pen(), [0.4, 0.8, 1.2], spacings, [0, 1, 3]);
    if ('error' in result) throw new Error(result.error);
    expect(result.pen.table).toEqual([[0.4, 0.25], [0.8, 0.35], [1.2, 0.6]]);
    const partial = combResult(pen(), [0.4, 0.8, 1.2], spacings, [-1, 1, null]);
    expect('error' in partial && partial.error).toMatch(/duas fileiras/);
  });

  it('cunha: aperto mínimo pela marca mais tardia de ida e volta, com folga, e aviso de atrito', () => {
    const layout = { from: 0, to: 1.5, length: 100 };
    const result = wedgeResult(pen(), layout, 2, 1, 8);
    if ('error' in result) throw new Error(result.error);
    expect(result.pen.depth_min).toBeCloseTo(0.375);  // marca 2 = 0,3 mm + 5% de 1,5
    expect(result.pen.depth_max).toBeCloseTo(1.125);  // marca 8 = 1,2 mm - folga
    expect(result.notes.join(' ')).toMatch(/atrito/);
    expect('error' in wedgeResult(pen(), layout, 6, null, 5)).toBe(true);
  });

  it('pontas: a distância em que o traço sumiu dá o aperto mínimo', () => {
    const result = waveResult(pen(), 1.5, 40, 8, 10);
    if ('error' in result) throw new Error(result.error);
    expect(result.pen.depth_min).toBeCloseTo(0.45);  // 10 de 40 mm = 0,375 mm + 5% de 1,5
    expect('error' in waveResult(pen({ depth_max: 0.5 }), 1.5, 40, 20, null)).toBe(true);
  });
});

describe('cartão dos testes', () => {
  function renderTests(over: { canGenerate?: boolean; hint?: string } = {}) {
    const handlers = { onSettings: vi.fn(), onPen: vi.fn(), onPick: vi.fn(), onGenerate: vi.fn(), onApply: vi.fn() };
    render(<ThicknessTests
      settings={settings({ padrao: pen(), 'sem-mola': pen({ mount: 'rigid', name: 'Caneta BIC sem mola' }) })}
      mounts={FALLBACK_MOUNTS} penTypes={TYPES} layouts={LAYOUTS} kind="drawing" canEdit canGenerate={over.canGenerate ?? true}
      hint={over.hint} {...handlers} />);
    return handlers;
  }

  it('mostra os quatro testes, a BIC selecionada e troca de suporte e de caneta', () => {
    const props = renderTests();
    expect(screen.getAllByRole('button', { name: /^\d · / }).map(b => b.querySelector('strong')?.textContent))
      .toEqual(['1 · Escada numerada', '2 · Pente de espessura', '3 · Cunha com régua', '4 · Onda e pontas']);
    expect((screen.getByLabelText('Tipo de caneta') as HTMLSelectElement).value).toBe('bic');
    expect(screen.getByText(/aperto de 0,4 a 1,5 mm/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Tipo de caneta'), { target: { value: 'canetinha' } });
    expect(props.onPen.mock.calls[0][0]).toMatchObject({ pen_type: 'canetinha', z_contact: null });
    fireEvent.click(screen.getByRole('button', { name: 'Sem mola' }));
    expect(props.onSettings.mock.calls[0][0].active_pen).toBe('sem-mola');
  });

  it('abrir um teste escolhe o trabalho, gera o plano e grava o resultado medido', () => {
    const props = renderTests();
    fireEvent.click(screen.getByRole('button', { name: /1 · Escada numerada/ }));
    expect(props.onPick).toHaveBeenCalledWith('ladder');
    fireEvent.click(screen.getByRole('button', { name: 'Gerar e validar o teste' }));
    expect(props.onGenerate).toHaveBeenCalledWith('ladder');
    for (const [label, value] of [['Linha 0,35 mm', '0.3'], ['Linha 0,75 mm', '0.4'], ['Linha 1,5 mm', '0.6']]) {
      const input = screen.getByLabelText(label);
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);
    }
    fireEvent.click(screen.getByRole('button', { name: 'Gravar resultado na caneta' }));
    expect(props.onApply).toHaveBeenCalledTimes(1);
    expect(props.onApply.mock.calls[0][0].table).toEqual([[0.35, 0.3], [0.75, 0.4], [1.5, 0.6]]);
    expect(props.onApply.mock.calls[0][0]).toMatchObject({ depth_min: 0.35, depth_max: 1.5 });
  });

  it('sem contato calibrado o botão de gerar fica desligado e explica o motivo', () => {
    renderTests({ canGenerate: false, hint: 'Antes, calibre a altura de contato.' });
    fireEvent.click(screen.getByRole('button', { name: /3 · Cunha com régua/ }));
    expect((screen.getByRole('button', { name: 'Gerar e validar o teste' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Antes, calibre a altura de contato.')).toBeTruthy();
    expect(screen.getByText(/0 a 1,5 mm de aperto/)).toBeTruthy();
  });
});
