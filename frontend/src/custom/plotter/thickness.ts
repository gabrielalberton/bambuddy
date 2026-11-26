import type { Calibration, MountKey, Pen, PenTypeInfo } from './api';

export type SweepVariant = 'reference' | 'speeds' | 'reverse';

export const SWEEP_VARIANTS: [SweepVariant, string][] = [
  ['reference', 'Referência (todas iguais)'],
  ['speeds', 'Velocidades alternadas (100% e 40%)'],
  ['reverse', 'Ordem invertida (de baixo para cima)'],
];

/** Pedido do plano para cada variação do teste: a referência não manda nada além do tipo. */
export function sweepOptions(variant: SweepVariant): { lines?: number; speeds?: number[]; reverse?: boolean } {
  if (variant === 'speeds') return { lines: 6, speeds: [1, 0.4] };
  if (variant === 'reverse') return { reverse: true };
  return {};
}

export function mm(value: number) {
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 3 });
}

/** Aplica os valores iniciais do tipo de caneta. Zera o contato e as medidas: outra caneta, outra ponta. */
export function applyPenType(pen: Pen, next: PenTypeInfo, previous: PenTypeInfo | undefined, mount: MountKey): Pen {
  const defaults = next.defaults[mount] ?? {};
  const oldName = previous?.defaults[mount]?.name;
  const keepName = !!pen.name && oldName !== undefined && pen.name !== oldName;
  return {
    ...pen, ...defaults, pen_type: next.key, z_contact: null, table: [],
    name: keepName ? pen.name : (defaults.name ?? pen.name),
  } as Pen;
}

export function calibrationText(calibration: Calibration) {
  if (calibration.test === 'zsweep' && calibration.z_from !== undefined && calibration.z_to !== undefined) {
    const speeds = calibration.speeds?.length && new Set(calibration.speeds).size > 1
      ? ` Velocidades por linha, de cima para baixo: ${calibration.speeds.map(mm).join(' · ')} mm/s.` : '';
    const order = calibration.order && calibration.order[0] !== 0 ? ' Desenhado de baixo para cima.' : '';
    return `Bico de Z ${mm(calibration.z_from)} a ${mm(calibration.z_to)} mm em ${mm(calibration.length ?? 0)} mm de linha; as verticais numeradas dizem o Z de cada posição.${speeds}${order}`;
  }
  return '';
}
