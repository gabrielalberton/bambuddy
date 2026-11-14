import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, fireEvent, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { render } from '../../__tests__/utils';
import { server } from '../../__tests__/mocks/server';
import { ModelSourcesPage } from '../../pages/ModelSourcesPage';
import { setModelCatalogOverride, isModelCatalogEnabled } from '../flags';
import { translate } from '../models/i18n';
import { PRINTER_FILTER_KEY } from '../models/utils';
import { printerA1, printerP1S, mockPrinterList, installMemoryStorage } from './fixtures';

// O SliceModal real busca presets/impressoras; aqui só importa que abriu com o arquivo salvo.
vi.mock('../../components/SliceModal', () => ({
  SliceModal: ({ source }: { source: { id: number; filename: string } }) => (
    <div role="dialog" aria-label="slice-modal">{`slice:${source.id}:${source.filename}`}</div>
  ),
}));

const SOURCES = {
  sources: [
    { id: 'makerworld', name: 'MakerWorld', enabled: true, disabled_reason: null, permission: 'makerworld', sorts: ['trending', 'popular', 'newest', 'relevance'], printer_filter: 'server', printer_filter_note: '' },
    { id: 'printables', name: 'Printables', enabled: true, disabled_reason: null, permission: 'library', sorts: ['popular', 'newest', 'relevance'], printer_filter: 'author_printer', printer_filter_note: '' },
    { id: 'thingiverse', name: 'Thingiverse', enabled: false, disabled_reason: 'needs key', permission: 'library', sorts: ['popular', 'newest', 'relevance'], printer_filter: 'none', printer_filter_note: '' },
  ],
  printer_models: ['A1'],
  makerworld_codes: ['N2S'],
  printables_printer_ids: [711],
};

const card = (provider: string, id: string, title: string) => ({
  provider, id, title, url: `https://x/${id}`, creator: 'Maker', thumbnail: null, downloads: 10, likes: 2,
});

const DETAIL = {
  ...card('makerworld', '42', 'Vase'),
  description_html: '<p>Nice</p><img src="https://evil/x.png">',
  images: [],
  license: 'BY',
  files: [
    { id: '6', name: 'A1 profile', format: '3mf', size: 1048576, sliceable: true, printer_match: 'native', printer: 'A1', metadata: { plates: [{}], requires_ams: true } },
    { id: '5', name: 'P1S profile', format: '3mf', size: null, sliceable: true, printer_match: 'other', printer: 'P1S', metadata: {} },
  ],
  preselect_file_id: '6',
  printer_models: ['A1'],
  metadata: {},
};

interface Captured { browse: URL[]; sources: URL[]; saves: { url: URL; body: unknown }[] }

function mockCatalog(): Captured {
  const captured: Captured = { browse: [], sources: [], saves: [] };
  server.use(
    http.get('*/api/v1/custom/models/sources', ({ request }) => {
      captured.sources.push(new URL(request.url));
      return HttpResponse.json(SOURCES);
    }),
    http.get('*/api/v1/custom/models/:source/categories', () => HttpResponse.json([{ id: '100', name: 'Art' }])),
    http.get('*/api/v1/custom/models/:source/browse', ({ request, params }) => {
      const url = new URL(request.url);
      captured.browse.push(url);
      const applied = params.source === 'makerworld' ? url.searchParams.get('printer_filter') === 'true' : url.searchParams.get('author_printer') === 'true';
      return HttpResponse.json({
        items: [card(String(params.source), params.source === 'makerworld' ? '42' : '7', `${params.source} model`)],
        total: 1,
        has_more: false,
        sort: url.searchParams.get('sort'),
        printer_models: ['A1'],
        printer_filter: { mode: params.source === 'makerworld' ? 'server' : 'author_printer', applied },
      });
    }),
    http.get('*/api/v1/custom/models/makerworld/42', () => HttpResponse.json(DETAIL)),
    http.post('*/api/v1/custom/models/makerworld/42/save', async ({ request }) => {
      captured.saves.push({ url: new URL(request.url), body: await request.json() });
      return HttpResponse.json({ library_file_id: 99, filename: 'vase.3mf', folder_id: 3, was_existing: false });
    }),
    http.get('*/library/folders', () => HttpResponse.json([])),
    http.get('*/makerworld/status', () => HttpResponse.json({ has_cloud_token: true, can_download: true })),
    http.get('*/makerworld/recent-imports', () => HttpResponse.json([])),
    http.get('*/manyfold/status', () => HttpResponse.json({ configured: false, url: '' })),
  );
  return captured;
}

let store: Map<string, string>;
beforeEach(() => {
  store = installMemoryStorage();
  window.history.replaceState({}, '', '/model-sources');
});
afterEach(() => {
  setModelCatalogOverride(null);
});

describe('flag do catálogo', () => {
  it('desligado nos testes do upstream por padrão; override liga', () => {
    expect(isModelCatalogEnabled()).toBe(false);
    setModelCatalogOverride('on');
    expect(isModelCatalogEnabled()).toBe(true);
  });

  it('com a flag desligada a página do upstream não muda (sem aba Catálogo)', async () => {
    mockCatalog();
    render(<ModelSourcesPage />);
    await screen.findByRole('tab', { name: /MakerWorld/ });
    expect(screen.queryByRole('tab', { name: /Catalog/ })).toBeNull();
  });
});

describe('aba Catálogo', () => {
  beforeEach(() => setModelCatalogOverride('on'));

  it('é a primeira aba e a padrão; a aba do importador MakerWorld continua', async () => {
    mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    const tabs = await screen.findAllByRole('tab');
    expect(tabs[0].textContent).toMatch(/Catalog/);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs.some((tab) => /MakerWorld/.test(tab.textContent ?? ''))).toBe(true);
    expect(await screen.findByText('makerworld model')).not.toBeNull();
  });

  it('filtro da impressora ligado por padrão (A1 da lista de impressoras) e lembrado ao desligar', async () => {
    const captured = mockCatalog();
    mockPrinterList([printerA1]);
    const { unmount } = render(<ModelSourcesPage />);
    const toggle = await screen.findByRole('switch', { name: /Only for my A1/ });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await waitFor(() => expect(captured.browse.some((u) => u.pathname.endsWith('/makerworld/browse'))).toBe(true));
    const mw = captured.browse.filter((u) => u.pathname.endsWith('/makerworld/browse')).at(-1)!;
    expect(mw.searchParams.get('printer_filter')).toBe('true');
    expect(mw.searchParams.getAll('printer_models')).toEqual(['A1']);
    expect(await screen.findByText(/Filtered by MakerWorld: models with a profile for A1/)).not.toBeNull();

    fireEvent.click(toggle);
    await waitFor(() => {
      const last = captured.browse.filter((u) => u.pathname.endsWith('/makerworld/browse')).at(-1)!;
      expect(last.searchParams.get('printer_filter')).toBe('false');
    });
    expect(store.get(PRINTER_FILTER_KEY)).toBe('0');
    unmount();

    render(<ModelSourcesPage />);
    const again = await screen.findByRole('switch', { name: /Only for my A1/ });
    expect(again.getAttribute('aria-checked')).toBe('false');
  });

  it('usa o modelo da impressora cadastrada (P1S), não "A1" fixo', async () => {
    const captured = mockCatalog();
    mockPrinterList([printerP1S]);
    render(<ModelSourcesPage />);
    expect(await screen.findByRole('switch', { name: /Only for my P1S/ })).not.toBeNull();
    await waitFor(() => {
      const last = captured.browse.filter((u) => u.pathname.endsWith('/makerworld/browse')).at(-1);
      expect(last?.searchParams.getAll('printer_models')).toEqual(['P1S']);
    });
  });

  it('sem impressora visível cai no fallback A1', async () => {
    mockCatalog();
    mockPrinterList([]);
    render(<ModelSourcesPage />);
    expect(await screen.findByRole('switch', { name: /Only for my A1/ })).not.toBeNull();
  });

  it('Printables: filtro marcado como não aplicável, com opção explícita "impressora do autor"', async () => {
    const captured = mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    expect(await screen.findByText(/Printables has no size or printer-profile data/)).not.toBeNull();
    const first = captured.browse.find((u) => u.pathname.endsWith('/printables/browse'))!;
    expect(first.searchParams.get('author_printer')).toBe('false');
    fireEvent.click(screen.getByRole('checkbox', { name: /author printed on a A1/ }));
    await waitFor(() => {
      const last = captured.browse.filter((u) => u.pathname.endsWith('/printables/browse')).at(-1)!;
      expect(last.searchParams.get('author_printer')).toBe('true');
    });
  });

  it('fonte sem chave aparece desligada e não é consultada', async () => {
    const captured = mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    expect(await screen.findByText(/Thingiverse · Not configured/)).not.toBeNull();
    await screen.findByText('printables model');
    expect(captured.browse.some((u) => u.pathname.includes('thingiverse'))).toBe(false);
  });

  it('detalhe: perfil da A1 primeiro e pré-selecionado; salvar e fatiar abrem o fluxo existente', async () => {
    const captured = mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    fireEvent.click(await screen.findByText('makerworld model'));
    expect(await screen.findByRole('heading', { name: 'Vase' })).not.toBeNull();
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios[0].closest('label')!.textContent).toMatch(/A1 profile/);
    expect(radios[0].checked).toBe(true);
    expect(within(radios[0].closest('label')!).getByText('Made for A1')).not.toBeNull();
    // Descrição sanitizada: sem imagem remota.
    expect(document.querySelector('img[src="https://evil/x.png"]')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Save to library/ }));
    expect(await screen.findByText(/Saved: vase.3mf/)).not.toBeNull();
    expect(captured.saves[0].body).toEqual({ file_id: '6', folder_id: null });

    fireEvent.click(screen.getByRole('button', { name: /Slice in Bambuddy/ }));
    expect((await screen.findByRole('dialog', { name: 'slice-modal' })).textContent).toBe('slice:99:vase.3mf');

    // Escolher outro perfil mostra o aviso de impressora diferente.
    fireEvent.click(radios[1]);
    expect(await screen.findByText(/This profile was not made for A1/)).not.toBeNull();
  });
});

describe('i18n do catálogo', () => {
  it('pt-BR e en, com fallback en', () => {
    expect(translate('pt-BR', 'printerFilter', { printer: 'A1' })).toBe('Só para minha A1');
    expect(translate('en', 'printerFilter', { printer: 'A1' })).toBe('Only for my A1');
    expect(translate('de', 'slice')).toBe('Slice in Bambuddy');
  });
});
