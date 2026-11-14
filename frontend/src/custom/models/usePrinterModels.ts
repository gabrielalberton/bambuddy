import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { mapModelCode } from '../../utils/printerModel';
import { useSinglePrinter } from '../useSinglePrinter';

/** Usado só quando o usuário não enxerga nenhuma impressora. */
export const FALLBACK_PRINTER_MODEL = 'A1';

export interface PrinterModels {
  /** Modelos (nome de exibição: "A1", "P1S"...), sem repetição. */
  models: string[];
  /** Rótulo curto para a UI ("A1" ou "A1/P1S"). */
  label: string;
  isFallback: boolean;
}

/**
 * Modelo(s) da(s) impressora(s) do usuário para o filtro do catálogo.
 * No modo impressora única é a única impressora (hook do fork); fora dele,
 * todos os modelos distintos de GET /printers/ (mesma query ['printers']).
 */
export function usePrinterModels(): PrinterModels {
  const { hasPermission } = useAuth();
  const canRead = hasPermission('printers:read');
  const { single, printer } = useSinglePrinter({ enabled: canRead });
  const { data } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters, enabled: canRead });
  const raw = single && printer ? [printer.model] : (data ?? []).map((p) => p.model);
  const models = Array.from(new Set(raw.filter((m): m is string => !!m).map((m) => mapModelCode(m))));
  if (models.length === 0) return { models: [FALLBACK_PRINTER_MODEL], label: FALLBACK_PRINTER_MODEL, isFallback: true };
  return { models, label: models.join('/'), isFallback: false };
}
