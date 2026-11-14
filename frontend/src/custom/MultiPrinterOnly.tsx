import type { ReactNode } from 'react';
import { useSinglePrinter } from './useSinglePrinter';

/**
 * Renderiza os filhos só quando NÃO estamos no modo impressora única.
 * `always` mantém os filhos mesmo no modo único (ex.: rótulo "sem impressora"
 * que continua informativo com uma impressora só).
 */
export function MultiPrinterOnly({ children, always = false }: { children: ReactNode; always?: boolean }) {
  const { single } = useSinglePrinter();
  if (single && !always) return null;
  return <>{children}</>;
}
