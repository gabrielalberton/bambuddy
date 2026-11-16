import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, render as rtlRender } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { server } from '../../__tests__/mocks/server';
import { render } from '../../__tests__/utils';
import i18n from '../../i18n';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { ToastProvider } from '../../contexts/ToastContext';
import { AuthProvider } from '../../contexts/AuthContext';
import { EmbeddedCameraViewer } from '../../components/EmbeddedCameraViewer';
import { CameraPage } from '../../pages/CameraPage';
import { setTwinOverride, isTwinModel } from '../twin/twinFlags';
import { resetTwinViewModeCache } from '../twin/useTwinView';
import { installMemoryStorage, mockPrinterList, printerA1, printerP1S } from './fixtures';

// O motor 3D precisa de WebGL (não existe no jsdom): no teste, o quadro do twin é um marcador.
vi.mock('../twin/DigitalTwinView', () => ({
  default: ({ printerId }: { printerId: number }) => <div data-testid="digital-twin-view">twin {printerId}</div>,
}));

async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}



function cameraStatusSpy() {
  const calls: string[] = [];
  server.use(
    http.post('/api/v1/printers/:id/camera/stop', () => HttpResponse.json({ success: true })),
    http.get('/api/v1/printers/:id/camera/status', ({ request }) => {
      calls.push(request.url);
      return HttpResponse.json({ active: false, stalled: false });
    }),
    http.get('/api/v1/printers/:id', ({ params }) =>
      HttpResponse.json(Number(params.id) === printerA1.id ? printerA1 : printerP1S),
    ),
  );
  return calls;
}

function renderCameraPage(printerId: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return rtlRender(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter initialEntries={[`/cameras/${printerId}`]}>
          <AuthProvider>
            <ThemeProvider>
              <ToastProvider>
                <Routes>
                  <Route path="/cameras/:printerId" element={<CameraPage />} />
                </Routes>
              </ToastProvider>
            </ThemeProvider>
          </AuthProvider>
        </MemoryRouter>
      </I18nextProvider>
    </QueryClientProvider>,
  );
}

describe('gêmeo digital: chave Câmera | 3D', () => {
  beforeEach(() => {
    installMemoryStorage();
    resetTwinViewModeCache();
    mockPrinterList([printerA1, printerP1S]);
  });

  afterEach(() => {
    setTwinOverride(null);
    resetTwinViewModeCache();
    vi.restoreAllMocks();
  });

  it('fica desligado nos testes do upstream (sem override): nenhuma chave, câmera intacta', async () => {
    cameraStatusSpy();
    render(<EmbeddedCameraViewer printerId={printerA1.id} printerName="A1" onClose={() => {}} />);
    await settle();
    expect(screen.queryByTestId('twin-switch')).toBeNull();
    expect(screen.getByAltText('Camera stream')).toBeTruthy();
  });

  it('só aparece para a A1', async () => {
    setTwinOverride(true);
    cameraStatusSpy();
    render(<EmbeddedCameraViewer printerId={printerP1S.id} printerName="P1S" onClose={() => {}} />);
    await settle();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('twin-switch')).toBeNull();
    expect(isTwinModel('A1')).toBe(true);
    expect(isTwinModel('N2S')).toBe(true);
    expect(isTwinModel('A1 Mini')).toBe(false);
    expect(isTwinModel('X1C')).toBe(false);
  });

  it('mostra câmera e 3D ao vivo lado a lado e expande com PiP sem desmontar o stream', async () => {
    setTwinOverride(true);
    cameraStatusSpy();
    render(<EmbeddedCameraViewer printerId={printerA1.id} printerName="A1" onClose={() => {}} />);
    const pair = await screen.findByTestId('camera-pair');
    const img = screen.getByAltText('Camera stream');
    expect(await screen.findByTestId('digital-twin-view')).toBeTruthy();
    expect(screen.queryByTestId('twin-switch')).toBeNull();
    expect(pair.getAttribute('data-layout')).toBe('split');

    fireEvent.click(screen.getByLabelText('Ampliar 3D'));
    expect(pair.getAttribute('data-layout')).toBe('twin');
    expect(screen.getByAltText('Camera stream')).toBe(img);
    expect(img.getAttribute('src')).toContain('/camera/stream');
    fireEvent.click(screen.getByLabelText('Ampliar câmera e trocar com 3D'));
    expect(pair.getAttribute('data-layout')).toBe('camera');
    fireEvent.click(screen.getByLabelText('Voltar às duas visualizações'));
    expect(pair.getAttribute('data-layout')).toBe('split');
  });

  it('na página da câmera também mostra as duas visualizações', async () => {
    setTwinOverride(true);
    cameraStatusSpy();
    renderCameraPage(printerA1.id);
    expect(await screen.findByTestId('camera-pair')).toBeTruthy();
    expect(await screen.findByTestId('digital-twin-view')).toBeTruthy();
  });
});
