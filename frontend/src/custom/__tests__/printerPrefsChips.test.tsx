import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PrinterPrefsChips } from '../printer/PrinterPrefsChips';

const fetchMock = vi.fn();

function ok(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

function renderChips(props: Partial<Parameters<typeof PrinterPrefsChips>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PrinterPrefsChips printerId={1} isPrinting={false} speedLevel={2} nozzleDiameter="0.4" canControl {...props} />
    </QueryClientProvider>,
  );
}

describe('PrinterPrefsChips', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/prefs')) return ok({ default_speed: 4, speed_level: 2, nozzle_diameter: '0.4', nozzle_options: ['0.2', '0.4'], apply_from_layer: 2 });
      if (url.includes('/nozzle')) return ok({ nozzle_diameter: '0.2', method: init?.method });
      return ok({ applied_now: false });
    });
  });

  it('mostra o bico e, parada, o padrão da próxima impressão', async () => {
    renderChips();
    expect(screen.getByTestId('custom-nozzle-chip').textContent).toContain('0.4 mm');
    await waitFor(() => expect(screen.getByTestId('custom-speed-chip').textContent).toMatch(/ludicrous|Ludicrous|printers.speed.ludicrous/));
  });

  it('troca o bico para 0.2', async () => {
    renderChips();
    fireEvent.click(screen.getByTestId('custom-nozzle-chip'));
    fireEvent.click(screen.getByText('0.2 mm'));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/1/nozzle?diameter=0.2'))).toBe(true));
  });

  it('não deixa trocar o bico imprimindo', () => {
    renderChips({ isPrinting: true });
    fireEvent.click(screen.getByTestId('custom-nozzle-chip'));
    expect((screen.getByText('0.2 mm') as HTMLButtonElement).disabled).toBe(true);
  });
});
