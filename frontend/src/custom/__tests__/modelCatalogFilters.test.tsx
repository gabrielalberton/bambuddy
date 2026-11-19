import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { render } from '../../__tests__/utils';
import { server } from '../../__tests__/mocks/server';
import { ModelSourcesPage } from '../../pages/ModelSourcesPage';
import { setCatalogFiltersOverride, setModelCatalogOverride, isCatalogFiltersEnabled } from '../flags';
import { FILTERS_KEY_PREFIX, sanitize } from '../models/filters';
import type { CatalogFilterSchema } from '../models/types';
import { printerA1, mockPrinterList, installMemoryStorage } from './fixtures';

const SOURCES = {
  sources: [
    { id: 'makerworld', name: 'MakerWorld', enabled: true, disabled_reason: null, permission: 'makerworld', sorts: ['trending', 'popular', 'newest', 'relevance', 'likes', 'boosts', 'random'], printer_filter: 'server', printer_filter_note: '' },
    { id: 'printables', name: 'Printables', enabled: true, disabled_reason: null, permission: 'library', sorts: ['popular', 'newest', 'relevance', 'rating', 'makes'], printer_filter: 'author_printer', printer_filter_note: '' },
  ],
  printer_models: ['A1'],
  makerworld_codes: ['N2S'],
  printables_printer_ids: [711],
};

const L = (pt: string, en = pt) => ({ pt, en });
const MW_SCHEMA: CatalogFilterSchema = {
  source: 'makerworld',
  origin: 'cfg2',
  sorts: ['trending', 'popular', 'newest', 'relevance', 'likes', 'boosts', 'random'],
  groups: [
    {
      id: 'model',
      label: L('Modelo', 'Model'),
      filters: [
        { id: 'model_tag', type: 'enum', label: L('Tipo de modelo', 'Model tag'), options: [{ value: 'cb', label: L('CyberBrick') }, { value: 'param', label: L('Paramétrico', 'Parametric') }] },
        { id: 'isPrintable', type: 'bool', label: L('Com perfil de impressão', 'Has a print profile'), options: [] },
      ],
    },
    {
      id: 'profile',
      label: L('Perfil de impressão', 'Print profile'),
      filters: [
        { id: 'nozzleDiameters', type: 'multi', label: L('Diâmetro do bico', 'Nozzle diameter'), options: [{ value: '0.2', label: L('0.2mm') }, { value: '0.4', label: L('0.4mm') }] },
        { id: 'printDuration', type: 'range', label: L('Tempo de impressão', 'Print time'), options: [{ value: '15', label: L('15 min') }, { value: '60', label: L('1 h', '1 hr') }] },
      ],
    },
  ],
};

const card = (provider: string, id: string, title: string, extra = {}) => ({
  provider, id, title, url: `https://x/${id}`, creator: 'Maker', thumbnail: null, downloads: 10, likes: 2, ...extra,
});

function mockCatalog() {
  const browse: URL[] = [];
  server.use(
    http.get('*/api/v1/custom/models/sources', () => HttpResponse.json(SOURCES)),
    http.get('*/api/v1/custom/models/:source/categories', () => HttpResponse.json([])),
    http.get('*/api/v1/custom/models/:source/filters', ({ params }) =>
      HttpResponse.json(params.source === 'makerworld' ? MW_SCHEMA : { source: params.source, origin: 'static', sorts: [], groups: [] }),
    ),
    http.get('*/api/v1/custom/models/:source/browse', ({ request, params }) => {
      const url = new URL(request.url);
      browse.push(url);
      const filters = JSON.parse(url.searchParams.get('filters') ?? '{}') as Record<string, unknown>;
      const cb = filters.model_tag === 'cb';
      return HttpResponse.json({
        items: [card(String(params.source), '42', cb ? 'Brick car' : `${params.source} model`, { cyberbrick: cb })],
        total: cb ? 8 : 100,
        has_more: false,
        sort: url.searchParams.get('sort'),
        printer_models: ['A1'],
        printer_filter: { mode: 'server', applied: true },
        filters,
      });
    }),
    http.get('*/library/folders', () => HttpResponse.json([])),
    http.get('*/makerworld/status', () => HttpResponse.json({ has_cloud_token: true, can_download: true })),
    http.get('*/makerworld/recent-imports', () => HttpResponse.json([])),
    http.get('*/manyfold/status', () => HttpResponse.json({ configured: false, url: '' })),
  );
  return browse;
}

const lastMw = (browse: URL[]) => browse.filter((u) => u.pathname.endsWith('/makerworld/browse')).at(-1)!;
const filtersOf = (u: URL) => JSON.parse(u.searchParams.get('filters') ?? '{}');

let store: Map<string, string>;
beforeEach(() => {
  store = installMemoryStorage();
  window.history.replaceState({}, '', '/model-sources?tab=catalog&src=makerworld');
  setModelCatalogOverride('on');
  setCatalogFiltersOverride('on');
});
afterEach(() => {
  setModelCatalogOverride(null);
  setCatalogFiltersOverride(null);
});

describe('filtro avançado do catálogo', () => {
  it('flag desligada: sem botão Filtros nem chave CyberBrick, busca sem filters', async () => {
    setCatalogFiltersOverride('off');
    const browse = mockCatalog();
    mockPrinterList([printerA1]);
    store.set(`${FILTERS_KEY_PREFIX}makerworld`, JSON.stringify({ model_tag: 'cb' }));
    render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    expect(screen.queryByRole('button', { name: /^Filters/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'CyberBrick' })).toBeNull();
    expect(lastMw(browse).searchParams.has('filters')).toBe(false);
    setCatalogFiltersOverride(null);
    expect(isCatalogFiltersEnabled()).toBe(false); // padrão nos testes
  });

  it('modal: aplica filtros, contador no botão, chips removíveis e persistência por fonte', async () => {
    const browse = mockCatalog();
    mockPrinterList([printerA1]);
    const { unmount } = render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    fireEvent.click(screen.getByRole('button', { name: /^Filters/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Filters · MakerWorld' });
    expect(new URLSearchParams(window.location.search).get('filters')).toBe('1');

    fireEvent.click(within(dialog).getByRole('switch', { name: 'Has a print profile' }));
    fireEvent.click(within(dialog).getByRole('button', { name: '0.2mm' }));
    fireEvent.click(within(dialog).getByRole('button', { name: '0.4mm' }));
    fireEvent.change(within(dialog).getByRole('combobox', { name: 'To' }), { target: { value: '60' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Apply \(3\)/ }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() =>
      expect(filtersOf(lastMw(browse))).toEqual({ isPrintable: true, nozzleDiameters: ['0.2', '0.4'], printDuration: [null, '60'] }),
    );
    expect(screen.getByRole('button', { name: /Filters · 3 active/ })).not.toBeNull();
    expect(JSON.parse(store.get(`${FILTERS_KEY_PREFIX}makerworld`)!)).toMatchObject({ isPrintable: true });

    // chip removível
    fireEvent.click(screen.getByRole('button', { name: 'Remove filter: Nozzle diameter: 0.2mm, 0.4mm' }));
    await waitFor(() => expect(filtersOf(lastMw(browse))).toEqual({ isPrintable: true, printDuration: [null, '60'] }));
    expect(screen.getByRole('button', { name: /Filters · 2 active/ })).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Remove filter: Print time: up to 1 hr' })).not.toBeNull();
    unmount();

    // lembrado ao reabrir (localStorage por fonte)
    const again = mockCatalog();
    render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    await waitFor(() => expect(filtersOf(lastMw(again))).toEqual({ isPrintable: true, printDuration: [null, '60'] }));
  });

  it('Limpar zera o rascunho; fechar sem aplicar não muda a busca', async () => {
    const browse = mockCatalog();
    mockPrinterList([printerA1]);
    store.set(`${FILTERS_KEY_PREFIX}makerworld`, JSON.stringify({ isPrintable: true }));
    render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    await waitFor(() => expect(filtersOf(lastMw(browse))).toEqual({ isPrintable: true }));
    fireEvent.click(screen.getByRole('button', { name: /^Filters/ }));
    let dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear' }));
    expect(within(dialog).getByRole('switch', { name: 'Has a print profile' }).getAttribute('aria-checked')).toBe('false');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(filtersOf(lastMw(browse))).toEqual({ isPrintable: true });

    fireEvent.click(screen.getByRole('button', { name: /^Filters/ }));
    dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(lastMw(browse).searchParams.has('filters')).toBe(false));
    expect(store.has(`${FILTERS_KEY_PREFIX}makerworld`)).toBe(false);
  });

  it('chave CyberBrick sempre na barra: aplica model_tag=cb e o card ganha o selo', async () => {
    const browse = mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    const toggle = screen.getByRole('button', { name: 'CyberBrick' });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect(await screen.findByText('Brick car')).not.toBeNull();
    expect(filtersOf(lastMw(browse))).toEqual({ model_tag: 'cb' });
    expect(screen.getByRole('button', { name: 'CyberBrick' }).getAttribute('aria-pressed')).toBe('true');
    // selo no card; sem chip duplicado acima da grade
    const cardButton = screen.getByText('Brick car').closest('button')!;
    expect(within(cardButton).getByText('CyberBrick')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /Remove filter/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Filters · 1 active/ })).not.toBeNull();
  });

  it('na visão "Todas" a chave CyberBrick leva para o MakerWorld filtrado', async () => {
    window.history.replaceState({}, '', '/model-sources?tab=catalog');
    const browse = mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    await screen.findByText('printables model');
    expect(screen.queryByRole('button', { name: /^Filters/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'CyberBrick' }));
    expect(await screen.findByText('Brick car')).not.toBeNull();
    expect(new URLSearchParams(window.location.search).get('src')).toBe('makerworld');
    expect(filtersOf(lastMw(browse))).toEqual({ model_tag: 'cb' });
  });

  it('ordenações próprias da fonte aparecem só com ela selecionada', async () => {
    mockCatalog();
    mockPrinterList([printerA1]);
    render(<ModelSourcesPage />);
    await screen.findByText('makerworld model');
    const select = screen.getByRole('combobox', { name: 'Sort' }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['trending', 'popular', 'newest', 'relevance', 'likes', 'boosts', 'random']);
    expect(Array.from(select.options).find((o) => o.value === 'likes')!.textContent).toBe('Most liked');
  });

  it('sanitize descarta filtro salvo que o esquema não conhece mais', () => {
    expect(
      sanitize({ evil: 'x', model_tag: 'gone', nozzleDiameters: ['0.2', '9'], printDuration: ['60', '15'], isPrintable: true }, MW_SCHEMA),
    ).toEqual({ nozzleDiameters: ['0.2'], isPrintable: true });
  });
});
