type Pose = Partial<Record<'x' | 'y' | 'z', number>>;

interface Program {
  total: number;
  posAt(time: number, out: Pose): unknown;
}

interface Tracker {
  locked: boolean;
  waiting: boolean;
  mode: string;
  vel(): number;
  T: number;
  p: Program;
  corr: number;
  diag: { vision?: number };
}

export function poseTimeShift(program: Program, samples: { programTime: number; pose: Pose }[]): number | null;

export class VisionMotion {
  reset(): void;
  observe(message: { ts: number; vision?: (Pose & { at: number }) | null }, now: number, tracker: Tracker | null): void;
  current(now: number): Pose | null;
  locked(now: number): boolean;
}
