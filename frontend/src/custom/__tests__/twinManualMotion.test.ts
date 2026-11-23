import { describe, expect, it } from 'vitest';
import { anchorTwinMotion, createManualMotion, listenToTwinMotion, previewTwinJog, resetTwinMotion, twinMotionStatus } from '../twin/manualMotion';

const homePose = { x: 128, y: 128, z: 20 };
const right = { x: 10, y: 0, z: 0 };
const up = { x: 0, y: 0, z: 1 };
const ready = { conn: { mqtt: true }, age: 0, s: { home_flag: 7, gcode_state: 'IDLE' } };

describe('manual motion in the A1 twin', () => {
  it('stays unknown after homing flags alone, then uses the explicit reference returned by the command', () => {
    const motion = createManualMotion();
    motion.observe(twinMotionStatus({ ...ready, s: { ...ready.s, home_flag: 3 } }, 0));
    motion.observe(twinMotionStatus(ready, 0));
    expect(motion.jog(right)).toBeUndefined();
    expect(motion.target).toBeNull();
    motion.anchor(homePose);
    expect(motion.target).toEqual(homePose);
    motion.jog(right);
    motion.observe(twinMotionStatus({ ...ready, s: { ...ready.s, gcode_state: 'PREPARE' } }, 0));
    expect(motion.target).toBeNull();
  });

  it('invalidates a reference when the printer or stream goes offline', () => {
    const motion = createManualMotion();
    for (const [msg, elapsed] of [
      [null, 0],
      [{ ...ready, s: { ...ready.s, home_flag: 0 } }, 0],
      [{ ...ready, conn: { mqtt: false } }, 0],
      [{ ...ready, age: 14 }, 2],
    ] as const) {
      motion.anchor(homePose);
      expect(motion.referenced).toBe(true);
      motion.observe(twinMotionStatus(msg, elapsed));
      expect(motion.referenced).toBe(false);
    }
  });

  it('moves before HTTP responds, scopes commands by printer and undoes only the failed jog', async () => {
    const motion = createManualMotion();
    const unlisten = listenToTwinMotion(1, motion);
    try {
      anchorTwinMotion(2, homePose);
      expect(motion.target).toBeNull();
      anchorTwinMotion(1, homePose);
      let reject = (_error: Error) => {};
      const failed = previewTwinJog(1, right, () => new Promise<void>((_, fn) => { reject = fn; }));
      expect(motion.target).toEqual({ ...homePose, x: 138 });
      await previewTwinJog(2, right, () => Promise.resolve());
      expect(motion.target).toEqual({ ...homePose, x: 138 });
      await previewTwinJog(1, up, () => Promise.resolve());
      expect(motion.target).toEqual({ x: 138, y: 128, z: 21 });
      reject(new Error('offline'));
      await expect(failed).rejects.toThrow('offline');
      expect(motion.target).toEqual({ ...homePose, z: 21 });
      resetTwinMotion(1);
      expect(motion.target).toBeNull();
    } finally {
      unlisten();
    }
  });

  it('discards rollbacks from an estimate invalidated by homing or lost telemetry', () => {
    const motion = createManualMotion();
    motion.anchor(homePose);
    const rollback = motion.jog(right);
    motion.reset();
    motion.anchor(homePose);
    const rollbackUp = motion.jog(up);
    rollback?.();
    expect(motion.target).toEqual({ ...homePose, z: 21 });
    rollbackUp?.();
    expect(motion.target).toEqual(homePose);
  });
});
