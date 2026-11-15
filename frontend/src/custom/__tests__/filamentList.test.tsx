/**
 * Filamentos em lista no card da impressora (modo impressora única).
 *
 * Renderiza a PrintersPage real com uma A1 + AMS Lite (4x PLA, slot 4 ativo) e
 * o spool externo vazio, e confere que os seletores da folha de estilo ainda
 * acham o DOM do upstream, a ordem das linhas, as colunas fixas, o destaque do
 * ativo, o vazio e que o toque no slot continua indo para o hover card/ações do
 * upstream.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../../__tests__/mocks/server';
import { render } from '../../__tests__/utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { setFilamentListOverride, setSinglePrinterModeOverride } from '../flags';
import {
  FILAMENT_LIST_CLASS,
  FILAMENT_LIST_KEEP_HEADER_CLASS,
  FILAMENT_LIST_SELECTORS,
  FILAMENT_ROW_COLUMNS,
} from '../printer/filamentList';
import { printerA1, installMemoryStorage } from './fixtures';

const tray = (id: number, remain: number) => ({
  id,
  tray_color: ['FF0000FF', '00AE42FF', 'FFFFFFFF', '000000FF'][id],
  tray_type: 'PLA',
  tray_sub_brands: 'PLA Basic',
  tray_id_name: '',
  tray_info_idx: 'GFA00',
  remain,
  k: 0.02,
  cali_idx: null,
  tag_uid: null,
  tray_uuid: null,
  nozzle_temp_min: 190,
  nozzle_temp_max: 230,
  state: 11,
});

const amsLite = {
  id: 0,
  humidity: 30,
  temp: 26,
  is_ams_ht: false,
  serial_number: 'AMSLITE0001',
  sw_ver: '1.0.0',
  dry_time: 0,
  dry_status: 0,
  dry_sub_status: 0,
  dry_sf_reason: [],
  module_type: 'ams_lite',
  tray: [tray(0, 80), tray(1, 45), tray(2, 100), tray(3, 12)],
};

const a1Status = {
  connected: true,
  state: 'IDLE',
  progress: 0,
  layer_num: 0,
  total_layers: 0,
  temperatures: { nozzle: 25, bed: 25, chamber: 25 },
  remaining_time: 0,
  filename: null,
  wifi_signal: -50,
  speed_level: 2,
  tray_now: 3,
  ams: [amsLite],
  vt_tray: [{ id: 254, tray_type: '', tray_color: '', remain: -1, k: 0, state: 0 }],
};

const sent: string[] = [];

function setup() {
  sent.length = 0;
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json([printerA1])),
    http.get('/api/v1/printers/:id/status', () => HttpResponse.json(a1Status)),
    http.get('/api/v1/queue/', () => HttpResponse.json([])),
    http.post('/api/v1/printers/:id/ams/:amsId/slot/:slotId/refresh', ({ request }) => {
      sent.push(new URL(request.url).pathname);
      return HttpResponse.json({ success: true, message: 'ok' });
    }),
  );
  render(<PrintersPage />);
}

async function rows(): Promise<HTMLElement[]> {
  await waitFor(() => {
    expect(document.querySelectorAll(FILAMENT_LIST_SELECTORS.row).length).toBe(5);
  });
  return Array.from(document.querySelectorAll<HTMLElement>(FILAMENT_LIST_SELECTORS.row));
}

beforeEach(() => {
  installMemoryStorage();
  setSinglePrinterModeOverride('on');
  setFilamentListOverride('on');
});
afterEach(() => {
  setSinglePrinterModeOverride(null);
  setFilamentListOverride(null);
});

describe('Filamentos em lista (modo impressora única)', () => {
  it('os seletores acham o DOM do upstream: cabeçalho da seção, cabeçalhos das unidades e grades', async () => {
    setup();
    await rows();
    const header = document.querySelectorAll(FILAMENT_LIST_SELECTORS.sectionHeader);
    expect(header).toHaveLength(1);
    expect(header[0].textContent).toContain('Filaments');

    const unitHeaders = Array.from(document.querySelectorAll(FILAMENT_LIST_SELECTORS.unitHeader));
    expect(unitHeaders.map((h) => h.textContent)).toEqual([
      expect.stringContaining('AMS'),
      expect.stringContaining('External'),
    ]);
    expect(unitHeaders[0].textContent).toContain('30%');

    expect(document.querySelectorAll(FILAMENT_LIST_SELECTORS.slotGrid)).toHaveLength(2);
    expect(document.querySelectorAll(FILAMENT_LIST_SELECTORS.slotWrapper)).toHaveLength(5);

    // a folha de estilo foi injetada e esconde os cabeçalhos
    expect(document.getElementById('custom-filament-list-style')).not.toBeNull();
    expect(getComputedStyle(header[0]).display).toBe('none');
    for (const h of unitHeaders) expect(getComputedStyle(h).display).toBe('none');
  });

  it('uma linha por slot, AMS 1-4 e depois o externo, com bolinha | material | barra (sem K)', async () => {
    setup();
    const list = await rows();
    const circles = list.map((r) => r.querySelector(':scope > div:first-of-type')!.textContent);
    expect(circles).toEqual(['1', '2', '3', '4', '1']);
    expect(list.map((r) => r.querySelector(':scope > div:nth-of-type(2)')!.textContent)).toEqual([
      'PLA', 'PLA', 'PLA', 'PLA', 'Empty',
    ]);
    expect(getComputedStyle(list[0].querySelector(':scope > div:nth-of-type(3)')!).display).toBe('none');

    for (const r of list) {
      // colunas fixas iguais em toda linha => toda barra começa e termina no mesmo x
      expect(getComputedStyle(r).gridTemplateColumns).toBe(FILAMENT_ROW_COLUMNS);
      const bar = r.lastElementChild as HTMLElement;
      expect(bar.className).toContain('overflow-hidden');
      expect(getComputedStyle(bar).gridColumn).toBe('3');
    }
    // nível: largura da barra interna = remain
    const fills = list.map((r) => (r.lastElementChild!.firstElementChild as HTMLElement | null)?.style.width ?? null);
    expect(fills).toEqual(['80%', '45%', '100%', '12%', null]);
  });

  it('destaca só o slot ativo (tray_now) e mostra o externo vazio esmaecido', async () => {
    setup();
    const list = await rows();
    expect(list.map((r) => r.className.includes('ring-bambu-green'))).toEqual([false, false, false, true, false]);
    expect(list[4].className).toContain('opacity-50');
    expect(list[4].lastElementChild!.childElementCount).toBe(0);
    expect(list[4].parentElement!.getAttribute('data-testid')).toBe('empty-slot');
  });

  it('tocar na linha abre o hover card do upstream e a ação vai para o handler original', async () => {
    const user = userEvent.setup();
    setup();
    const list = await rows();
    fireEvent.mouseEnter(list[1].parentElement!);
    await user.click(await screen.findByRole('button', { name: 'Re-read RFID' }));
    await waitFor(() => expect(sent).toEqual([`/api/v1/printers/${printerA1.id}/ams/0/slot/1/refresh`]));

    // linha do externo vazio: menu de slot vazio do upstream (Load/atribuir)
    fireEvent.mouseEnter(list[4].parentElement!);
    expect(await screen.findByRole('button', { name: 'Load' })).not.toBeNull();
  });

  it('com o spool externo oculto mantém o cabeçalho (é nele que fica o olho para mostrar de novo)', async () => {
    localStorage.setItem('printerHiddenExternalSpools', JSON.stringify({ [printerA1.id]: true }));
    setup();
    await waitFor(() => expect(document.querySelectorAll(FILAMENT_LIST_SELECTORS.row).length).toBe(4));
    const container = document.querySelector(`.${FILAMENT_LIST_CLASS}`)!;
    expect(container.classList.contains(FILAMENT_LIST_KEEP_HEADER_CLASS)).toBe(true);
    expect(document.querySelectorAll(FILAMENT_LIST_SELECTORS.sectionHeader)).toHaveLength(0);
  });

  it('flag off ou fora do modo impressora única: grade original sem a classe', async () => {
    setFilamentListOverride('off');
    setup();
    await waitFor(() => expect(screen.getAllByTestId('filament-slot').length).toBe(4));
    expect(document.querySelector(`.${FILAMENT_LIST_CLASS}`)).toBeNull();
  });

  it('modo impressora única desligado: grade original', async () => {
    setSinglePrinterModeOverride('off');
    setup();
    await waitFor(() => expect(screen.getAllByTestId('filament-slot').length).toBe(4));
    expect(document.querySelector(`.${FILAMENT_LIST_CLASS}`)).toBeNull();
  });
});
