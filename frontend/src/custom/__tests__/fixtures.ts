import { vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../../__tests__/mocks/server';

export const printerA1 = {
  id: 7,
  name: 'A1 do Gabriel',
  ip_address: '192.168.1.50',
  serial_number: '03919A000000001',
  access_code: '12345678',
  model: 'A1',
  enabled: true,
  is_active: true,
  nozzle_diameter: 0.4,
  nozzle_type: 'stainless_steel',
  location: 'Oficina',
  auto_archive: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

export const printerP1S = { ...printerA1, id: 8, name: 'P1S', model: 'P1S', serial_number: '01P00A000000002', location: null };

export const idleStatus = {
  connected: true,
  state: 'IDLE',
  awaiting_plate_clear: false,
  progress: 0,
  layer_num: 0,
  total_layers: 0,
  temperatures: { nozzle: 25, bed: 25, chamber: 25 },
  remaining_time: 0,
  filename: null,
  wifi_signal: -50,
  vt_tray: [],
};

/** Responde /printers/ com a lista dada e o status de cada uma como ocioso. */
export function mockPrinterList(list: unknown[]) {
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json(list)),
    http.get('/api/v1/printers/:id/status', () => HttpResponse.json(idleStatus)),
  );
}

/**
 * O setup do upstream troca o localStorage por vi.fn() vazios; aqui ele vira
 * um armazenamento em memória de verdade (as preferências salvas importam).
 */
export function installMemoryStorage(): Map<string, string> {
  const store = new Map<string, string>();
  vi.mocked(localStorage.getItem).mockImplementation((k: string) => (store.has(k) ? store.get(k)! : null));
  vi.mocked(localStorage.setItem).mockImplementation((k: string, v: string) => { store.set(k, String(v)); });
  vi.mocked(localStorage.removeItem).mockImplementation((k: string) => { store.delete(k); });
  vi.mocked(localStorage.clear).mockImplementation(() => store.clear());
  return store;
}
