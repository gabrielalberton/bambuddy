import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Jog } from '../plotter/api';
import { ContactAdjust } from '../plotter/Contact';

const SPRING = [-1, -0.5, -0.1, 0.1, 0.5, 1];
const RIGID = [-1, -0.1, -0.02, 0.02, 0.1, 1];

function setup(over: { jog?: Jog | null; steps?: number[]; canStart?: boolean; canControl?: boolean; reason?: string } = {}) {
  const handlers = { onStart: vi.fn(), onMove: vi.fn(), onFinish: vi.fn() };
  const view = render(<ContactAdjust jog={over.jog} contact={null} steps={over.steps ?? SPRING} hint="Desça até encostar."
    canControl={over.canControl ?? true} canStart={over.canStart ?? true} reason={over.reason} {...handlers} />);
  return { ...handlers, ...view };
}

const jog = (over: Partial<Jog> = {}): Jog => ({ z: 20, floor: 0.6, max: 40, settling: 0, ...over });

describe('altura de contato', () => {
  it('o homing só sai depois da confirmação, que vale para um toque só', () => {
    const props = setup();
    const start = screen.getByRole('button', { name: 'Fazer homing e levar a caneta ao centro' }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(start.disabled).toBe(false);
    fireEvent.click(start);
    expect(props.onStart).toHaveBeenCalledTimes(1);
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
  });

  it('com a A1 ocupada ou sem permissão o botão fica desligado e diz o motivo', () => {
    setup({ canStart: false, reason: 'A1 imprimindo.' });
    fireEvent.click(screen.getByRole('checkbox'));
    expect((screen.getByRole('button', { name: /Fazer homing/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('A1 imprimindo.')).toBeTruthy();
  });

  it('descer e subir usam o passo escolhido, começando pelo maior', () => {
    const props = setup({ jog: jog() });
    expect(screen.getByRole('status').textContent).toMatch(/Z 20,00 mm/);
    fireEvent.click(screen.getByRole('button', { name: /Descer 1/ }));
    expect(props.onMove).toHaveBeenLastCalledWith(19);
    fireEvent.click(screen.getByRole('button', { name: '0,1 mm' }));
    fireEvent.click(screen.getByRole('button', { name: /Subir 0,1/ }));
    expect(props.onMove).toHaveBeenLastCalledWith(19.1);
    fireEvent.click(screen.getByRole('button', { name: /Descer 0,1/ }));
    expect(props.onMove).toHaveBeenLastCalledWith(19);
  });

  it('sem mola oferece o passo de 0,02 mm e não passa do piso', () => {
    const props = setup({ jog: jog({ z: 0.61 }), steps: RIGID });
    expect(screen.getAllByRole('button', { pressed: false }).map(b => b.textContent)).toContain('0,02 mm');
    fireEvent.click(screen.getByRole('button', { name: '0,02 mm' }));
    expect((screen.getByRole('button', { name: /Descer 0,02/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Subir 0,02/ }));
    expect(props.onMove).toHaveBeenLastCalledWith(0.63);
  });

  it('OK grava o contato; cancelar levanta sem gravar; nada trava enquanto a A1 se move', () => {
    const props = setup({ jog: jog() });
    fireEvent.click(screen.getByRole('button', { name: 'OK, salvar contato e levantar' }));
    expect(props.onFinish).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar e levantar sem salvar' }));
    expect(props.onFinish).toHaveBeenLastCalledWith(false);
    props.rerender(<ContactAdjust jog={jog({ settling: 2 })} contact={null} steps={SPRING} hint="" canControl canStart
      onStart={props.onStart} onMove={props.onMove} onFinish={props.onFinish} />);
    expect(screen.queryByText(/aguarde/)).toBeNull();
    for (const name of [/Descer/, /Subir/, /OK, salvar/, /Cancelar/]) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(false);
    }
  });

  it('toques seguidos somam os passos sem esperar a A1 responder', () => {
    const props = setup({ jog: jog({ settling: 3 }) });
    for (let i = 0; i < 3; i += 1) fireEvent.click(screen.getByRole('button', { name: /Descer 1/ }));
    expect(props.onMove.mock.calls.map(call => call[0])).toEqual([19, 18, 17]);
    expect(screen.getByRole('status').textContent).toMatch(/Z 17,00 mm/);
    props.rerender(<ContactAdjust jog={jog({ z: 17 })} contact={null} steps={SPRING} hint="" canControl canStart
      onStart={props.onStart} onMove={props.onMove} onFinish={props.onFinish} />);
    fireEvent.click(screen.getByRole('button', { name: /Subir 1/ }));
    expect(props.onMove).toHaveBeenLastCalledWith(18);
  });

  it('se o movimento falha, volta a valer a altura informada pela A1', async () => {
    const props = setup({ jog: jog() });
    props.onMove.mockRejectedValueOnce(new Error('falhou'));
    fireEvent.click(screen.getByRole('button', { name: /Descer 1/ }));
    await vi.waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Z 20,00 mm/));
  });
});
