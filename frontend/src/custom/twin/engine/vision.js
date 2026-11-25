// Observações dos dois detectores da câmera, na hora de captura estimada.
const AXES = ['x', 'y', 'z'];
const MAX_AGE = 0.85;

export function poseTimeShift(program, samples) {
  if (samples.length < 4) return null;
  const varied = AXES.some((axis) => {
    const positions = samples.map((s) => s.pose[axis]).filter(Number.isFinite);
    return positions.length >= 3 && Math.max(...positions) - Math.min(...positions) >= (axis === 'z' ? 4 : 8);
  });
  if (!varied) return null;

  const position = {};
  function error(shift) {
    let sum = 0, n = 0;
    for (const sample of samples) {
      const t = sample.programTime + shift;
      if (t < 0 || t > program.total) return Infinity;
      program.posAt(t, position);
      for (const axis of AXES) {
        const seen = sample.pose[axis];
        if (!Number.isFinite(seen)) continue;
        sum += Math.min(35, Math.abs(seen - position[axis]));
        n++;
      }
    }
    return sum / n;
  }

  const options = [];
  for (let i = -200; i <= 200; i++) {
    const shift = i * 0.04;
    options.push([error(shift), shift]);
  }
  options.sort((a, b) => a[0] - b[0]);
  let [cost, shift] = options[0];
  const coarse = shift;
  for (let i = -5; i <= 5; i++) {
    const candidate = coarse + i * 0.008;
    const next = error(candidate);
    if (next < cost) [cost, shift] = [next, candidate];
  }
  const alternative = options.find(([, alt]) => Math.abs(alt - shift) > 0.22)?.[0];
  if (cost > 7 || !(alternative > cost * 1.25 + 0.45)) return null;
  return shift;
}

export class VisionMotion {
  constructor() { this.reset(); }

  reset() {
    this.lastStamp = -Infinity;
    this.pose = null;
    this.captureAt = -Infinity;
    this.samples = [];
    this.tracker = null;
    this.lockedAt = -Infinity;
  }

  observe(msg, now, tracker) {
    const frame = msg.vision;
    if (!frame || !Number.isFinite(frame.at)) {
      this.pose = null;
      return;
    }
    if (frame.at <= this.lastStamp) return;
    const age = msg.ts - frame.at;
    if (!Number.isFinite(age) || age > MAX_AGE || age < -0.05) return;
    this.lastStamp = frame.at;
    this.captureAt = now - Math.max(0, age);
    this.pose = Object.fromEntries(AXES.filter((key) => Number.isFinite(frame[key])).map((key) => [key, frame[key]]));
    if (this.tracker !== tracker) {
      this.samples = [];
      this.lockedAt = -Infinity;
      this.tracker = tracker;
    }
    if (!tracker?.locked || tracker.waiting || tracker.mode !== 'running' || tracker.vel() < 0.2) {
      this.samples = [];
      this.lockedAt = -Infinity;
      return;
    }
    if (Object.keys(this.pose).length === 0) return;

    const programTime = tracker.T - age * tracker.vel();
    this.samples.push({ at: this.captureAt, pose: this.pose, programTime });
    this.samples = this.samples.filter((s) => s.at > now - 1.55).slice(-9);
    const shift = poseTimeShift(tracker.p, this.samples);
    if (shift === null) return;
    // O estimador existente absorve a correção gradualmente e mantém suas esperas.
    tracker.corr = shift;
    this.lockedAt = now;
    tracker.diag.vision = (tracker.diag.vision || 0) + 1;
  }

  current(now) {
    return now - this.captureAt <= MAX_AGE ? this.pose : null;
  }

  locked(now) {
    return now - this.lockedAt < 0.95;
  }
}
