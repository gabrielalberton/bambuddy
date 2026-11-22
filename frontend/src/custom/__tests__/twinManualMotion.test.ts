import { describe, expect, it } from 'vitest';
import { createManualMotion, listenToTwinMotion, previewTwinJog, resetTwinMotion, twinMotionStatus } from '../twin/manualMotion';

const base = { x: 40, y: 170, z: 90 };
const right = { x: 10, y: 0, z: 0 };
const up = { x: 0, y: 0, z: 1 };
const ready = { conn: { mqtt: true }, age: 0, s: { home_flag: 7, gcode_state: 'IDLE' } };

describe('manual motion in the A1 twin', () => {
  it('requires live telemetry, all three homed axes and an idle printer', () => {
    expect(twinMotionStatus(null, 0)).toEqual({ homed: false, canJog: false });
    expect(twinMotionStatus({ ...ready, s: { ...ready.s, home_flag: 3 } }, 0).canJog).toBe(false);
    expect(twinMotionStatus(ready, 0)).toEqual({ homed: true, canJog: true });
    expect(twinMotionStatus({ ...ready, s: { ...ready.s, gcode_state: 'RUNNING' } }, 0))
      .toEqual({ homed: true, canJog: false });
    expect(twinMotionStatus({ ...ready, conn: { mqtt: false } }, 0).canJog).toBe(false);
    expect(twinMotionStatus({ ...ready, age: 14 }, 2).canJog).toBe(false);
  });

  it('moves before HTTP responds, scopes commands by printer and undoes only the failed jog', async () => {
    const motion = createManualMotion();
    const unlisten = listenToTwinMotion(1, { jog: (delta) => motion.jog(base, delta), reset: motion.reset });
    try {
      let reject = (_error: Error) => {};
      const failed = previewTwinJog(1, right, () => new Promise<void>((_, fn) => { reject = fn; }));
      expect(motion.target).toEqual({ ...base, x: 50 });
      await previewTwinJog(2, right, () => Promise.resolve());
      expect(motion.target).toEqual({ ...base, x: 50 });
      await previewTwinJog(1, up, () => Promise.resolve());
      expect(motion.target).toEqual({ ...base, x: 50, z: 91 });
      reject(new Error('offline'));
      await expect(failed).rejects.toThrow('offline');
      expect(motion.target).toEqual({ ...base, z: 91 });
      resetTwinMotion(1);
      expect(motion.target).toBeNull();
    } finally {
      unlisten();
    }
  });

  it('discards rollbacks from an estimate invalidated by homing or lost telemetry', () => {
    const motion = createManualMotion();
    const rollback = motion.jog(base, right);
    motion.reset();
    const rollbackUp = motion.jog(base, up);
    rollback();
    expect(motion.target).toEqual({ ...base, z: 91 });
    rollbackUp();
    expect(motion.target).toBeNull();
  });
});
