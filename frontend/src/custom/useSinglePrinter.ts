import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type Printer } from '../api/client';
import { getSinglePrinterMode } from './flags';

export interface SinglePrinterState {
  /** true quando a UI deve se comportar como "uma impressora só". */
  single: boolean;
  /** A impressora única (undefined enquanto carrega ou fora do modo). */
  printer: Printer | undefined;
  printers: Printer[];
  isLoading: boolean;
}

/** Última contagem de impressoras vista, para não piscar a UI multi-impressora enquanto a lista carrega. */
export const LAST_PRINTER_COUNT_KEY = 'custom.singlePrinter.lastCount';

const OFF: SinglePrinterState = { single: false, printer: undefined, printers: [], isLoading: false };

function readLastCount(): number | null {
  try {
    const raw = localStorage.getItem(LAST_PRINTER_COUNT_KEY);
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeLastCount(count: number): void {
  try {
    localStorage.setItem(LAST_PRINTER_COUNT_KEY, String(count));
  } catch {
    /* sem localStorage: só perde a proteção contra o piscar */
  }
}

function useSinglePrinterActive(enabled: boolean): SinglePrinterState {
  const mode = getSinglePrinterMode();
  // Mesma query (['printers'] + api.getPrinters) que as páginas do upstream usam:
  // o React Query deduplica, então não há requisição extra.
  const { data, isLoading } = useQuery({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
    enabled,
  });
  const count = data?.length;
  useEffect(() => {
    if (count !== undefined) writeLastCount(count);
  }, [count]);

  const printers = data ?? [];
  let single: boolean;
  if (mode === 'on') {
    single = true;
  } else if (data) {
    single = data.length === 1;
  } else {
    // Ainda carregando: repete a última decisão conhecida.
    single = readLastCount() === 1;
  }
  return { single, printer: single ? printers[0] : undefined, printers, isLoading };
}

/**
 * Modo impressora única. `enabled` segue a mesma ideia do React Query: false
 * não busca a lista (útil quando o usuário não tem printers:read), mas ainda
 * usa o cache e a última contagem conhecida.
 */
export function useSinglePrinter(options: { enabled?: boolean } = {}): SinglePrinterState {
  // O modo não muda durante a vida da página (só por override em teste, antes
  // do render), então a ordem dos hooks é estável.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return getSinglePrinterMode() === 'off' ? OFF : useSinglePrinterActive(options.enabled ?? true);
}

/**
 * Resolve sozinho um campo "qual impressora" no modo impressora única: quando
 * `when` for true (ex.: campo ainda vazio), chama `select` com a impressora.
 * Evita que o arquivo do upstream precise importar useEffect só para o gancho.
 */
export function useAutoSelectSinglePrinter(when: boolean, select: (printer: Printer) => void): void {
  const { single, printer } = useSinglePrinter();
  const selectRef = useRef(select);
  selectRef.current = select;
  useEffect(() => {
    if (when && single && printer) selectRef.current(printer);
  }, [when, single, printer]);
}
