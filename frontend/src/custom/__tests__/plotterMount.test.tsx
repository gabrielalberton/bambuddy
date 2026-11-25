import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Pen, Settings } from '../plotter/api';
import { PenFields } from '../plotter/Controls';
import { MountPicker } from '../plotter/Mount';
import { FALLBACK_MOUNTS, selectMount } from '../plotter/mounts';

const [SPRING, RIGID] = FALLBACK_MOUNTS;

function pen(over: Partial<Pen> = {}): Pen {
  return {
    name: 'Caneta com mola', mount: 'spring', pen_type: 'bic', offset_x: 0, offset_y: -32, z_contact: 4.2, lift: 3,
    depth_min: 0.2, depth_max: 1.2, max_compression: 3, line_width: 0.5, draw_speed: 25, travel_speed: 100,
    z_speed: 10, dwell_ms: 0, use_mesh: false, table: [[0.2, 0.4], [1.2, 1.4]], ...over,
  };
}

function settings(pens: Record<string, Pen>, active = 'padrao'): Settings {
  return {
    machine: { plate_w: 256, plate_h: 256, nozzle_x: [0, 256], nozzle_y: [0, 254] },
    pens, active_pen: active, paper: { x: 23, y: 0, w: 210, h: 297, margin: 5, thickness: 0.1 }, placement: null,
  };
}

describe('modos do suporte', () => {
  it('troca para o perfil do outro modo sem misturar calibrações', () => {
    const both = settings({ padrao: pen(), 'sem-mola': pen({ name: 'Sem mola', mount: 'rigid', z_contact: 5.1 }) });
    const next = selectMount(both, RIGID);
    expect(next.active_pen).toBe('sem-mola');
    expect(next.pens.padrao.z_contact).toBe(4.2);
    expect(selectMount(next, RIGID)).toBe(next);
  });

  it('cria um perfil sem mola descalibrado, com malha e limites do modo, quando não existe', () => {
    const next = selectMount(settings({ padrao: pen() }), RIGID);
    const rigid = next.pens[next.active_pen];
    expect(next.active_pen).toBe('sem-mola');
    expect(rigid).toMatchObject({ mount: 'rigid', z_contact: null, table: [], use_mesh: true, max_compression: 0.6, offset_y: -32 });
    expect(next.pens.padrao.mount).toBe('spring');
  });

  it('o seletor mostra o modo ativo e devolve o perfil escolhido', () => {
    const onChange = vi.fn();
    const both = settings({ padrao: pen(), 'sem-mola': pen({ mount: 'rigid' }) });
    render(<MountPicker settings={both} mounts={FALLBACK_MOUNTS} onChange={onChange} />);
    expect(screen.getByRole('button', { name: 'Com mola' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Sem mola' }));
    expect(onChange.mock.calls[0][0].active_pen).toBe('sem-mola');
  });

  it('sem mola a malha é obrigatória e os limites de aperto são menores', () => {
    render(<PenFields pen={pen({ mount: 'rigid', use_mesh: true })} mount={RIGID} onChange={vi.fn()} />);
    const mesh = screen.getByRole('checkbox', { name: /malha de nivelamento/ }) as HTMLInputElement;
    expect(mesh.checked && mesh.disabled).toBe(true);
    expect((screen.getByLabelText('Limite da ponta (mm)') as HTMLInputElement).max).toBe('2');
    expect(SPRING.compression_limit).toBe(8);
  });
});
