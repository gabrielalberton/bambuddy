import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSinglePrinter, LAST_PRINTER_COUNT_KEY } from '../useSinglePrinter';
import { getSinglePrinterMode, setSinglePrinterModeOverride, SINGLE_PRINTER_MODE_STORAGE_KEY } from '../flags';
import { printerA1, printerP1S, mockPrinterList, installMemoryStorage } from './fixtures';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('flags', () => {
  beforeEach(() => { installMemoryStorage(); });
  afterEach(() => {
    setSinglePrinterModeOverride(null);
    localStorage.removeItem(SINGLE_PRINTER_MODE_STORAGE_KEY);
  });

  it('fica desligado nos testes por padrão (suíte do upstream intacta)', () => {
    localStorage.setItem(SINGLE_PRINTER_MODE_STORAGE_KEY, 'on');
    expect(getSinglePrinterMode()).toBe('off');
  });

  it('aceita override explícito', () => {
    setSinglePrinterModeOverride('auto');
    expect(getSinglePrinterMode()).toBe('auto');
  });
});

describe('useSinglePrinter', () => {
  beforeEach(() => { installMemoryStorage(); });
  afterEach(() => setSinglePrinterModeOverride(null));

  it("'off' nunca é single e não precisa de QueryClient", () => {
    const { result } = renderHook(() => useSinglePrinter());
    expect(result.current.single).toBe(false);
  });

  it("'auto' com uma impressora: single + impressora resolvida", async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    const { result } = renderHook(() => useSinglePrinter(), { wrapper });
    await waitFor(() => expect(result.current.printer?.id).toBe(7));
    expect(result.current.single).toBe(true);
    expect(localStorage.getItem(LAST_PRINTER_COUNT_KEY)).toBe('1');
  });

  it("'auto' com duas impressoras: não é single", async () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1, printerP1S]);
    const { result } = renderHook(() => useSinglePrinter(), { wrapper });
    await waitFor(() => expect(result.current.printers).toHaveLength(2));
    expect(result.current.single).toBe(false);
    expect(result.current.printer).toBeUndefined();
  });

  it("'auto' carregando: repete a última contagem conhecida (sem piscar)", () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    localStorage.setItem(LAST_PRINTER_COUNT_KEY, '1');
    const { result } = renderHook(() => useSinglePrinter(), { wrapper });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.single).toBe(true);
  });

  it("'auto' carregando sem histórico: não é single", () => {
    setSinglePrinterModeOverride('auto');
    mockPrinterList([printerA1]);
    const { result } = renderHook(() => useSinglePrinter(), { wrapper });
    expect(result.current.single).toBe(false);
  });

  it("'on' força single mesmo com duas impressoras", async () => {
    setSinglePrinterModeOverride('on');
    mockPrinterList([printerA1, printerP1S]);
    const { result } = renderHook(() => useSinglePrinter(), { wrapper });
    await waitFor(() => expect(result.current.printer?.id).toBe(7));
    expect(result.current.single).toBe(true);
  });
});
