import type { Calibration, MountKey, Pen, PenTypeInfo, TestLayouts } from './api';

export type TestKind = 'ladder' | 'comb' | 'wedge' | 'wave';
export const TEST_KINDS: TestKind[] = ['ladder', 'comb', 'wedge', 'wave'];

export const TEST_INFO: Record<TestKind, { title: string; summary: string; steps: string[] }> = {
  ladder: {
    title: '1 · Escada numerada',
    summary: 'Uma linha por aperto, com o valor escrito ao lado. Dá a curva aperto → largura.',
    steps: [
      'Plote o teste e espere a tinta secar. Cada linha tem 50 mm e fica no meio de uma fileira da grade de 10 mm.',
      'Meça a largura de cada linha com régua, lupa ou foto ampliada; numa foto, os quadrados de 10 mm servem de escala.',
      'Deixe em branco as linhas que não marcaram e escolha o maior aperto com traço bom.',
    ],
  },
  comb: {
    title: '2 · Pente de espessura',
    summary: 'Células hachuradas com espaçamento crescente: onde o traço é mais largo que o espaçamento, a célula fecha.',
    steps: [
      'Plote o teste. O número em cima de cada coluna é o espaçamento das linhas (mm); a grade passa entre as células.',
      'Em cada fileira, ache a última célula que virou mancha cheia, sem branco entre as linhas.',
      'A largura fica entre essa célula e a seguinte; não precisa de paquímetro.',
    ],
  },
  wedge: {
    title: '3 · Cunha com régua',
    summary: 'A ida vai do aperto zero ao máximo e a volta desce; a grade numerada é a régua. Dá o aperto mínimo e o máximo.',
    steps: [
      'Plote o teste. A linha de cima (→) vai da esquerda para a direita, apertando cada vez mais.',
      'Leia nos números da grade onde a ida começou a marcar e onde a volta (←) parou de marcar. Aceita decimais: 2,5 é o meio entre 2 e 3.',
      'Se o traço passou do ponto (borrou, raspou ou a ponta abriu), anote essa marca também.',
    ],
  },
  wave: {
    title: '4 · Onda e pontas',
    summary: 'Uma linha longa com o aperto oscilando em ondas cada vez mais curtas e traços que afinam até sumir.',
    steps: [
      'Plote o teste. A primeira fileira é a onda: engrossa e afina do aperto mínimo ao máximo do perfil.',
      'Onde a onda para de afinar entre os picos, a caneta (ou a mola) não acompanha mais: evite detalhes mais curtos que isso.',
      'Cada fileira de baixo é uma ponta com rampa do número escrito ao lado (mm). Pela grade, meça a quantos mm da ponta o traço sumiu, na entrada (esquerda) e na saída (direita).',
    ],
  },
};

export function isTest(kind: string): kind is TestKind {
  return (TEST_KINDS as string[]).includes(kind);
}

export function mm(value: number) {
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 3 });
}

const round3 = (value: number) => Math.round(value * 1000) / 1000;

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

/** Apertos do teste: os do plano gerado agora (iguais aos impressos) ou os do perfil atual. */
export function testDepths(kind: 'ladder' | 'comb', layouts: TestLayouts | undefined, calibration?: Calibration) {
  if (calibration?.test === kind && calibration.rows?.length) return calibration.rows.map(row => row.depth);
  return layouts?.[kind].depths ?? [];
}

type Result = { pen: Pen; notes: string[] } | { error: string };

/** Largura nunca diminui com mais aperto (o backend recusa): iguala à anterior e avisa. */
function monotone(rows: [number, number][], notes: string[]): [number, number][] {
  let changed = false;
  const out = rows.map(([depth, width], index) => {
    const before = index ? rows.slice(0, index).reduce((max, row) => Math.max(max, row[1]), 0) : 0;
    if (width < before) changed = true;
    return [depth, Math.max(width, before)] as [number, number];
  });
  if (changed) notes.push('Medidas que diminuíram com mais aperto foram igualadas à anterior.');
  return out;
}

export function ladderResult(pen: Pen, depths: number[], widths: (number | null)[], best: number | null): Result {
  const marked = depths.map((depth, index) => [depth, widths[index]] as const)
    .filter((row): row is readonly [number, number] => row[1] !== null && row[1] > 0)
    .map(([depth, width]) => [depth, width] as [number, number]);
  if (marked.length < 2) return { error: 'Preencha a largura de pelo menos duas linhas que marcaram.' };
  const notes: string[] = [];
  const table = monotone(marked, notes);
  const depthMin = table[0][0];
  const depthMax = best !== null && best >= depthMin ? best : table.at(-1)![0];
  if (depthMax <= depthMin) return { error: 'O maior aperto bom tem que ser maior que o primeiro que marcou.' };
  notes.unshift(`Aperto ${mm(depthMin)} a ${mm(depthMax)} mm; ${table.length} medidas; traço de ${mm(table[0][1])} a ${mm(table.at(-1)![1])} mm.`);
  return { pen: { ...pen, table, depth_min: depthMin, depth_max: depthMax, line_width: table[0][1] }, notes };
}

/** ``closed[i]``: índice da última célula fechada na fileira i; -1 = nenhuma fechou; null = não medida. */
export function combResult(pen: Pen, depths: number[], spacings: number[], closed: (number | null)[]): Result {
  const notes: string[] = [];
  const rows: [number, number][] = [];
  depths.forEach((depth, index) => {
    const cell = closed[index];
    if (cell === null || cell === undefined) return;
    if (cell < 0) {
      notes.push(`Aperto ${mm(depth)} mm: mais fino que ${mm(spacings[0])} mm, ficou de fora.`);
      return;
    }
    const width = cell >= spacings.length - 1 ? spacings.at(-1)! : (spacings[cell] + spacings[cell + 1]) / 2;
    rows.push([depth, round3(width)]);
  });
  if (rows.length < 2) return { error: 'Escolha a última célula fechada em pelo menos duas fileiras.' };
  const table = monotone(rows, notes);
  notes.unshift(`${table.length} medidas; traço de ${mm(table[0][1])} a ${mm(table.at(-1)![1])} mm.`);
  return { pen: { ...pen, table, line_width: table[0][1] }, notes };
}

export function wedgeDepth(layout: { from: number; to: number; length: number }, mark: number) {
  return layout.from + (layout.to - layout.from) * Math.min(1, Math.max(0, mark * 10 / layout.length));
}

export function wedgeResult(
  pen: Pen, layout: { from: number; to: number; length: number },
  forward: number | null, back: number | null, tooWide: number | null,
): Result {
  if (forward === null && back === null) return { error: 'Informe pelo menos onde a ida começou a marcar.' };
  const margin = 0.05 * (layout.to - layout.from);
  const starts = [forward, back].filter((mark): mark is number => mark !== null).map(mark => wedgeDepth(layout, mark));
  const depthMin = round3(Math.min(pen.max_compression, Math.max(...starts) + margin));
  const depthMax = tooWide === null ? pen.depth_max : round3(wedgeDepth(layout, tooWide) - margin);
  if (depthMax <= depthMin) {
    return { error: tooWide === null
      ? `O aperto mínimo (${mm(depthMin)} mm) passou do máximo do perfil; informe onde o traço passou do ponto.`
      : 'A marca de “passou do ponto” tem que ficar depois de onde começou a marcar.' };
  }
  const notes = [`Aperto ${mm(depthMin)} a ${mm(depthMax)} mm (com folga de ${mm(round3(margin))} mm).`];
  if (forward !== null && back !== null) {
    const gap = Math.abs(wedgeDepth(layout, forward) - wedgeDepth(layout, back));
    const high = pen.mount === 'rigid' ? 0.03 : 0.15;
    notes.push(gap > high
      ? `Ida e volta diferem ${mm(round3(gap))} mm de aperto: atrito no suporte. Confira o tubo e os adaptadores.`
      : `Ida e volta diferem ${mm(round3(gap))} mm de aperto.`);
  }
  return { pen: { ...pen, depth_min: depthMin, depth_max: depthMax }, notes };
}

export function waveResult(
  pen: Pen, peak: number, ramp: number, entry: number | null, exit: number | null,
): Result {
  if (entry === null && exit === null) return { error: 'Informe a quantos mm da ponta o traço sumiu.' };
  const depthAt = (distance: number) => peak * Math.min(1, Math.max(0, distance / ramp));
  const margin = 0.05 * peak;
  const starts = [entry, exit].filter((value): value is number => value !== null).map(depthAt);
  const depthMin = round3(Math.max(...starts) + margin);
  if (depthMin >= pen.depth_max) {
    return { error: `O traço só aparece perto do aperto máximo (${mm(depthMin)} mm): aumente o aperto máximo ou recalibre o contato.` };
  }
  const notes = [`Aperto mínimo ${mm(depthMin)} mm (a ponta some abaixo de ${mm(round3(Math.max(...starts)))} mm).`];
  if (entry !== null && exit !== null && Math.abs(entry - exit) > ramp * 0.25) {
    notes.push('Entrada e saída diferem bastante: a caneta demora a responder ao subir ou descer.');
  }
  return { pen: { ...pen, depth_min: depthMin }, notes };
}

export function calibrationText(calibration: Calibration, rigid: boolean) {
  if (calibration.test === 'wedge' && calibration.to !== undefined) {
    return `Cunha de 0 a ${mm(calibration.to)} mm de aperto em ${calibration.length} mm (marcas 0 a ${calibration.marks}).`;
  }
  if (calibration.test === 'wave' && calibration.to !== undefined) {
    return `Onda de ${mm(calibration.from ?? 0)} a ${mm(calibration.to)} mm em ${calibration.length} mm; pontas com rampa de ${(calibration.tapers ?? []).map(t => mm(t.ramp)).join(', ')} mm.`;
  }
  if (!calibration.rows?.length) return '';
  const what = rigid ? 'Apertos' : 'Compressões';
  const spacing = calibration.spacings?.length ? ` · espaçamentos ${calibration.spacings.map(mm).join(' · ')} mm` : '';
  return `${what}, de cima para baixo: ${calibration.rows.map(row => mm(row.depth)).join(' · ')} mm${spacing}`;
}
