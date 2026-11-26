import type { MountInfo, MountKey, Pen, PenTypeInfo, Settings } from './api';

/** Fallback quando o backend ainda não manda `mounts` (mesmos valores de engine/profile.py). */
export const FALLBACK_MOUNTS: MountInfo[] = [
  {
    key: 'spring', name: 'Com mola', depth_limit: 6, compression_limit: 8, jog_steps: [-1, -0.5, -0.1, 0.1, 0.5, 1],
    needs_mesh: false, approach_speed: null,
    defaults: { name: 'Caneta com mola', depth_min: 0.2, depth_max: 1.2, max_compression: 3, z_speed: 10 },
  },
  {
    key: 'rigid', name: 'Sem mola', depth_limit: 2, compression_limit: 2, jog_steps: [-1, -0.1, -0.02, 0.02, 0.1, 1],
    needs_mesh: true, approach_speed: 2,
    defaults: { name: 'Caneta sem mola', depth_min: 0.05, depth_max: 0.4, max_compression: 0.6, z_speed: 5 },
  },
];

type About = { summary: string; use: string; good: string[]; bad: string[]; contact: string };

export const MOUNT_ABOUT: Record<MountKey, About> = {
  spring: {
    summary: 'A caneta desliza no tubo contra a mola; descer o Z comprime a mola.',
    use: 'Esferográfica, gel, fineliner e marcador de ponta firme.',
    good: [
      'Absorve ondulação da folha e da mesa sem falhar nem esmagar.',
      'A largura muda aos poucos com o Z: calibração tolerante.',
      'Protege a ponta e a impressora de aperto demais.',
    ],
    bad: [
      'Folga do tubo deixa o traço tremido e os cantos abertos.',
      'Atrito: a mesma altura dá pressões diferentes descendo e subindo.',
      'A força mínima da mola limita o traço mais leve.',
    ],
    contact: 'Desça até a ponta encostar no papel e pare no toque, antes de a mola ceder. O teste de altura mostra a partir de onde a linha marca.',
  },
  rigid: {
    summary: 'Caneta travada no tubo, sem a mola: só a própria ponta cede.',
    use: 'Caneta pincel (Pentel Pocket Brush, Tombow Fudenosuke) e feltro macio.',
    good: [
      'Traço preciso, sem folga lateral.',
      'Resposta imediata ao Z, sem histerese do suporte.',
      'Melhor controle de largura com ponta de pincel.',
    ],
    bad: [
      'Décimos de milímetro mudam muito a largura.',
      'A folha precisa estar plana e presa; malha de nivelamento obrigatória.',
      'Aperto demais quebra ponta dura e marca a chapa.',
    ],
    contact: 'Perto do papel use passos de 0,02 mm e pare no primeiro toque da ponta.',
  },
};

export function mountOf(pen: Pen | undefined): MountKey {
  return pen?.mount === 'rigid' ? 'rigid' : 'spring';
}

/** Torna ativo o perfil do modo escolhido; cria um (mesmo tipo de caneta, valores do modo) se ainda não existir. */
export function selectMount(settings: Settings, mount: MountInfo, penTypes: PenTypeInfo[] = []): Settings {
  const active = settings.pens[settings.active_pen];
  if (mountOf(active) === mount.key) return settings;
  const found = Object.keys(settings.pens).find(id => mountOf(settings.pens[id]) === mount.key);
  if (found) return { ...settings, active_pen: found };
  const base = mount.key === 'rigid' ? 'sem-mola' : 'com-mola';
  let id = base;
  for (let n = 2; settings.pens[id]; n++) id = `${base}-${n}`;
  const typed = penTypes.find(type => type.key === active.pen_type)?.defaults[mount.key];
  const pen: Pen = {
    ...active, ...mount.defaults, ...typed, mount: mount.key, z_contact: null, table: [],
    use_mesh: mount.needs_mesh || active.use_mesh,
  } as Pen;
  return { ...settings, pens: { ...settings.pens, [id]: pen }, active_pen: id };
}
