import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { PlateClear } from '../plotter/PlateClear';

it('só aparece quando o Bambuddy espera a mesa liberada e confirma com um toque', () => {
  const onConfirm = vi.fn();
  const view = render(<PlateClear needed={false} allowed onConfirm={onConfirm} />);
  expect(screen.queryByRole('button', { name: /Mesa liberada/ })).toBeNull();
  view.rerender(<PlateClear needed allowed onConfirm={onConfirm} />);
  fireEvent.click(screen.getByRole('button', { name: /Mesa liberada/ }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

it('sem permissão o botão fica desligado e explica por quê', () => {
  render(<PlateClear needed allowed={false} onConfirm={vi.fn()} />);
  expect((screen.getByRole('button', { name: /Mesa liberada/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/não tem permissão/)).toBeTruthy();
});
