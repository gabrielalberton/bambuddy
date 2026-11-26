import type { Calibration, MountKey, Pen, PenTypeInfo } from './api';

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
    return `Bico de Z ${mm(calibration.z_from)} a ${mm(calibration.z_to)} mm em ${mm(calibration.length ?? 0)} mm de linha; as verticais numeradas dizem o Z de cada posição.`;
  }
  return '';
}
