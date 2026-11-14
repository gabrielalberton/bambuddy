import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { render } from '../../__tests__/utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { PrinterSelector } from '../../components/PrintModal/PrinterSelector';
import { CameraLauncher } from '../../components/CameraLauncher';
import { PrintModal } from '../../components/PrintModal';
import { http, HttpResponse } from 'msw';
import { server } from '../../__tests__/mocks/server';
import type { Printer } from '../../api/client';
import { setSinglePrinterModeOverride } from '../flags';
import { LAST_PRINTER_COUNT_KEY } from '../useSinglePrinter';
import { printerA1, printerP1S, mockPrinterList, installMemoryStorage } from './fixtures';

beforeEach(() => {
  installMemoryStorage();
});
afterEach(() => {
  setSinglePrinterModeOverride(null);
});

describe('PrintersPage — barra de ferramentas no modo impressora única', () => {
  it('esconde busca, filtros, ordenação, cam wall e seleção em massa; mantém tamanho de card', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    // Preferências salvas que, sem neutralizar, esconderiam a única impressora.
    localStorage.setItem('printerStatusFilter', 'printing');
    localStorage.setItem('hideDisconnectedPrinters', 'true');
    localStorage.setItem('printerPageView', 'camwall');
    localStorage.setItem('printerSortBy', 'location');

    render(<PrintersPage />);

    expect(await screen.findByText('A1 do Gabriel')).not.toBeNull();
    expect(screen.queryByPlaceholderText('Search printers...')).toBeNull();
    expect(screen.queryByText('Hide offline')).toBeNull();
    expect(screen.queryByTitle('Cam wall')).toBeNull();
    expect(screen.queryByTitle('Select')).toBeNull();
    // agrupamento por local desligado (sem cabeçalho "Oficina (1)")
    expect(screen.queryByText('Oficina')).toBeNull();
    // o seletor de tamanho de card continua
    expect(screen.getByRole('button', { name: 'XL' })).not.toBeNull();
    // a escolha persistida não é apagada (desligar o modo devolve tudo)
    expect(localStorage.getItem('printerStatusFilter')).toBe('printing');
  });

  it('com duas impressoras (auto) mantém a UI original', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1, printerP1S]);
    render(<PrintersPage />);
    expect(await screen.findByText('A1 do Gabriel')).not.toBeNull();
    expect(screen.getByPlaceholderText('Search printers...')).not.toBeNull();
    expect(screen.getByTitle('Cam wall')).not.toBeNull();
  });
});

describe('PrinterSelector no modo impressora única', () => {
  const printers = [printerA1] as unknown as Printer[];

  it('impressora já selecionada: sem lista de botões nem chave de modelo', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    localStorage.setItem(LAST_PRINTER_COUNT_KEY, '1');
    render(
      <PrinterSelector
        printers={printers}
        selectedPrinterIds={[7]}
        onMultiSelect={vi.fn()}
        allowMultiple
        assignmentMode="printer"
        onAssignmentModeChange={vi.fn()}
        onTargetModelChange={vi.fn()}
        slicedForModel="A1"
      />,
    );
    await waitFor(() => expect(screen.queryByText('Specific Printer')).toBeNull());
    expect(screen.queryByText('A1 do Gabriel')).toBeNull();
    expect(screen.queryByText('Select at least one printer')).toBeNull();
  });

  it('nada selecionado: a lista volta, para o usuário poder escolher', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    localStorage.setItem(LAST_PRINTER_COUNT_KEY, '1');
    const onMultiSelect = vi.fn();
    render(
      <PrinterSelector
        printers={printers}
        selectedPrinterIds={[]}
        onMultiSelect={onMultiSelect}
        allowMultiple
        assignmentMode="printer"
        onAssignmentModeChange={vi.fn()}
        onTargetModelChange={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByText('A1 do Gabriel'));
    expect(onMultiSelect).toHaveBeenCalledWith([7]);
    expect(screen.queryByText('Specific Printer')).toBeNull();
  });

  it('modo desligado: chave "Specific Printer" e lista como no upstream', () => {
    render(
      <PrinterSelector
        printers={printers}
        selectedPrinterIds={[7]}
        onMultiSelect={vi.fn()}
        allowMultiple
        assignmentMode="printer"
        onAssignmentModeChange={vi.fn()}
        onTargetModelChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Specific Printer')).not.toBeNull();
    expect(screen.getByText('A1 do Gabriel')).not.toBeNull();
  });
});

describe('CameraLauncher no modo impressora única', () => {
  it('o clique abre e fecha direto a câmera da única impressora, sem menu', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    render(<CameraLauncher placement="down" />);
    const button = await screen.findByRole('button', { name: 'Cameras' });
    // espera a lista de impressoras chegar (o hook decide "single" por ela)
    await waitFor(() => expect(localStorage.getItem(LAST_PRINTER_COUNT_KEY)).toBe('1'));

    fireEvent.click(button);
    expect(screen.queryByRole('region', { name: 'Cameras' })).toBeNull();
    await waitFor(() => expect(JSON.parse(localStorage.getItem('openEmbeddedCameras') || '[]')).toEqual([
      expect.objectContaining({ id: 7, scope: 'app' }),
    ]));

    fireEvent.click(button);
    await waitFor(() => expect(localStorage.getItem('openEmbeddedCameras')).toBeNull());
    expect(screen.queryByRole('region', { name: 'Cameras' })).toBeNull();
  });
});

describe('PrintModal no modo impressora única', () => {
  it('autoseleciona a única impressora, esconde a lista e envia com printer_id', async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.get('/api/v1/archives/:id/plates', () => HttpResponse.json({ is_multi_plate: false, plates: [] })),
      http.get('/api/v1/archives/:id/filament-requirements', () => HttpResponse.json({ filaments: [] })),
      http.post('/api/v1/queue/', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: 1, status: 'pending' });
      }),
    );
    render(<PrintModal mode="create" archiveId={1} archiveName="Benchy.3mf" onClose={vi.fn()} onSuccess={vi.fn()} />);

    // Sem lista de impressoras e sem aviso "Select at least one printer": a seleção automática aconteceu.
    await waitFor(() => expect(localStorage.getItem(LAST_PRINTER_COUNT_KEY)).toBe('1'));
    await waitFor(() => expect(screen.queryByText('Select at least one printer')).toBeNull());
    expect(screen.queryByText('A1 do Gabriel')).toBeNull();
    expect(screen.queryByText('Specific Printer')).toBeNull();

    const submit = document.querySelector('button[type="submit"]') as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].printer_id).toBe(7);
  });
});
