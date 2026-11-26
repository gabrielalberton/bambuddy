import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { HistoryItem, Pen, PenTypeInfo, Settings } from '../plotter/api';
import { DrawingHistory } from '../plotter/History';
import { FALLBACK_MOUNTS, selectMount } from '../plotter/mounts';
import { ZSweepTest } from '../plotter/Thickness';
import { applyPenType, calibrationText } from '../plotter/thickness';

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

describe('cartão do teste de altura', () => {
  function renderTest(over: { canGenerate?: boolean; hint?: string } = {}) {
    const handlers = { onSettings: vi.fn(), onPen: vi.fn(), onGenerate: vi.fn() };
    render(<ZSweepTest
      settings={settings({ padrao: pen(), 'sem-mola': pen({ mount: 'rigid', name: 'Caneta BIC sem mola' }) })}
      mounts={FALLBACK_MOUNTS} penTypes={TYPES} canEdit canGenerate={over.canGenerate ?? true}
      hint={over.hint} {...handlers} />);
    return handlers;
  }

  it('é um teste só: explica Z 5 a 8, gera o plano e troca de suporte e de caneta', () => {
    const props = renderTest();
    expect(screen.getByRole('heading', { name: 'Teste de altura (Z)' })).toBeTruthy();
    expect(screen.queryByText(/Escada|Pente|Cunha|Onda/)).toBeNull();
    expect(screen.getByText(/começa apertada \(Z 5\) e termina com o bico no ar \(Z 8\)/)).toBeTruthy();
    expect((screen.getByLabelText('Tipo de caneta') as HTMLSelectElement).value).toBe('bic');
    fireEvent.change(screen.getByLabelText('Tipo de caneta'), { target: { value: 'canetinha' } });
    expect(props.onPen.mock.calls[0][0]).toMatchObject({ pen_type: 'canetinha', z_contact: null });
    fireEvent.click(screen.getByRole('button', { name: 'Sem mola' }));
    expect(props.onSettings.mock.calls[0][0].active_pen).toBe('sem-mola');
    fireEvent.click(screen.getByRole('button', { name: 'Gerar e validar o teste' }));
    expect(props.onGenerate).toHaveBeenCalledTimes(1);
  });

  it('sem contato calibrado o botão de gerar fica desligado e explica o motivo', () => {
    renderTest({ canGenerate: false, hint: 'Antes, calibre a altura de contato.' });
    expect((screen.getByRole('button', { name: 'Gerar e validar o teste' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Antes, calibre a altura de contato.')).toBeTruthy();
  });

  it('descreve o teste gerado com o Z inicial e final', () => {
    expect(calibrationText({ test: 'zsweep', z_from: 5, z_to: 8, length: 168 })).toMatch(/Z 5 a 8 mm em 168 mm/);
    expect(calibrationText({})).toBe('');
  });
});
