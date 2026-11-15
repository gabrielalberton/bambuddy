/**
 * Filamentos em lista no card da impressora (modo impressora única).
 *
 * Não reimplementa nada do upstream: os tiles de slot continuam sendo os do
 * PrintersPage (mesmos FilamentHoverCard/EmptySlotHoverCard, ações, cadeia de
 * nível Spoolman → inventário → AMS, anel do slot ativo). Só o contêiner da
 * seção ganha uma classe e esta folha de estilo reorganiza o DOM existente:
 *
 *  - some o cabeçalho "FILAMENTS" (rótulo, botão de backup, linha, olho) e o
 *    cabeçalho de cada unidade ("AMS-A" + umidade/temperatura, "External");
 *  - unidades e slots ficam empilhados, um slot por linha;
 *  - cada linha é uma grade `bolinha | material | K | barra` com as três
 *    primeiras colunas de largura fixa, então toda barra (= 100%) começa e
 *    termina no mesmo x, qualquer que seja o texto.
 *
 * Os seletores dependem da estrutura do upstream (v1.3.1); o teste
 * `custom/__tests__/filamentList.test.tsx` confere que cada um ainda acha o
 * elemento certo — se o upstream mexer na seção, é ele que quebra primeiro.
 */
import { useInsertionEffect } from 'react';
import { useSinglePrinter } from '../useSinglePrinter';
import { isFilamentListEnabled } from '../flags';

export const FILAMENT_LIST_CLASS = 'custom-filament-list';
/** Mantém o cabeçalho quando o spool externo está oculto: é nele que fica o olho para mostrá-lo de volta. */
export const FILAMENT_LIST_KEEP_HEADER_CLASS = 'custom-filament-list--keep-header';

/** Larguras fixas das colunas antes da barra (iguais em toda linha). */
export const FILAMENT_ROW_COLUMNS = '1.375rem 3.75rem 3rem minmax(0, 1fr)';

const S = `.${FILAMENT_LIST_CLASS}`;

/** Seletores usados pela folha de estilo (exportados para o teste conferir o DOM do upstream). */
export const FILAMENT_LIST_SELECTORS = {
  /** Cabeçalho da seção: "FILAMENTS", backup do AMS, linha e o olho do externo. */
  sectionHeader: `${S}:not(.${FILAMENT_LIST_KEEP_HEADER_CLASS}) > :first-child`,
  /** `flex flex-wrap` com um cartão por unidade (AMS, AMS-HT, externo). */
  units: `${S} > :last-child`,
  unit: `${S} > :last-child > div`,
  /** Cabeçalho de cada unidade ("AMS-A" + umidade/temperatura, "External"). */
  unitHeader: `${S} > :last-child > div > :first-child`,
  /** Grade de slots de cada unidade. */
  slotGrid: `${S} > :last-child > div > .grid`,
  slotWrapper: `${S} > :last-child > div > .grid > div`,
  /** Conteúdo visual do slot (filho do gatilho do hover card). */
  row: `${S} [data-testid="filament-slot"] > div:first-child, ${S} [data-testid="empty-slot"] > div:first-child`,
} as const;

const row = (suffix: string) =>
  FILAMENT_LIST_SELECTORS.row
    .split(', ')
    .map((sel) => `${sel}${suffix}`)
    .join(', ');

export const FILAMENT_LIST_CSS = `
${FILAMENT_LIST_SELECTORS.sectionHeader},
${FILAMENT_LIST_SELECTORS.unitHeader},
${S} [data-testid="ams3h-dryer"],
${S} [data-testid="ams3h-dryer-info"] { display: none !important; }

${FILAMENT_LIST_SELECTORS.units} {
  display: flex; flex-direction: column; gap: 0.25rem;
  padding: 0.375rem; border-radius: 10px; background: var(--color-bambu-dark);
}
${FILAMENT_LIST_SELECTORS.unit} {
  flex: none !important; width: 100%; min-width: 0 !important; max-width: none !important;
  padding: 0; background: transparent; border-radius: 0;
}
${FILAMENT_LIST_SELECTORS.unit} > * { margin-block: 0; }
${FILAMENT_LIST_SELECTORS.slotGrid} { display: flex; flex-direction: column; gap: 0.25rem; }
${FILAMENT_LIST_SELECTORS.slotWrapper} { min-width: 0 !important; max-width: none !important; }

${row('')} {
  display: grid; grid-template-columns: ${FILAMENT_ROW_COLUMNS};
  column-gap: 0.5rem; align-items: center; text-align: left;
  min-height: 2.25rem; padding: 0.25rem 0.625rem;
}
${row(' > *')} { grid-row: 1; margin: 0; }
${row(' > div:first-of-type')} {
  grid-column: 1; width: 1.375rem; height: 1.375rem; margin: 0;
}
${row(' > div:first-of-type > span')} { font-size: calc(var(--pc-t9, 9px) + 1px); }
${row(' > div:nth-of-type(2)')} {
  grid-column: 2; font-size: calc(var(--pc-t9, 9px) + 3px); line-height: 1.2;
}
${row(' > div:nth-of-type(3):not(:last-child)')} {
  grid-column: 3; font-size: calc(var(--pc-t8, 8px) + 2px); line-height: 1.2;
}
${row(' > div:last-child')} { grid-column: 4; height: 0.5rem; margin: 0; }
`;

const STYLE_ID = 'custom-filament-list-style';

function ensureStyles(): void {
  if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = FILAMENT_LIST_CSS;
  document.head.appendChild(style);
}

/**
 * className do contêiner da seção de filamentos (gancho no PrinterCard).
 * Fora do modo impressora única, ou com `custom.filamentList`='off', devolve
 * `base` intacto.
 */
export function useFilamentListClass(base: string, externalSpoolHidden = false): string {
  const { single } = useSinglePrinter();
  const enabled = single && isFilamentListEnabled();
  useInsertionEffect(() => {
    if (enabled) ensureStyles();
  }, [enabled]);
  if (!enabled) return base;
  return [base, FILAMENT_LIST_CLASS, externalSpoolHidden ? FILAMENT_LIST_KEEP_HEADER_CLASS : '']
    .filter(Boolean)
    .join(' ');
}
