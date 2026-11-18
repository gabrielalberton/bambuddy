import { describe, it, expect } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { render } from '../../__tests__/utils';
import { QueueChip } from '../printer/CardExtras';

describe('QueueChip (card compacto)', () => {
  it('não aparece com a fila vazia', () => {
    render(<QueueChip count={0} />);
    expect(screen.queryByTestId('custom-queue-chip')).toBeNull();
  });

  it('mostra a contagem e abre a fila', () => {
    render(
      <Routes>
        <Route path="/" element={<QueueChip count={2} />} />
        <Route path="/queue" element={<p>página da fila</p>} />
      </Routes>,
    );
    const chip = screen.getByTestId('custom-queue-chip');
    expect(chip.textContent).toContain('2');
    fireEvent.click(chip);
    expect(screen.getByText('página da fila')).toBeTruthy();
  });
});
