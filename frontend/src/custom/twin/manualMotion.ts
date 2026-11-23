import { ACTIVE_PRINT_STATES, IDLE_PRINTER_STATES } from '../../utils/printer';
import { isTwinEnabled, isTwinModel } from './twinFlags';

type Position = { x: number; y: number; z: number };

type Jog = (delta: Position) => (() => void) | undefined;
type Listener = { jog: Jog; reset: () => void; anchor: (position: Position) => void };

const listeners = new Map<number, Set<Listener>>();

export function listenToTwinMotion(printerId: number, listener: Listener) {
  const group = listeners.get(printerId) ?? new Set<Listener>();
  group.add(listener);
  listeners.set(printerId, group);
  return () => {
    group.delete(listener);
    if (!group.size) listeners.delete(printerId);
  };
}

export async function previewTwinJog<T>(printerId: number, delta: Position, send: () => Promise<T>) {
  const undo = Array.from(listeners.get(printerId) ?? [], (listener) => listener.jog(delta));
  try {
    return await send();
  } catch (error) {
    undo.forEach((rollback) => rollback?.());
    throw error;
  }
}

export function resetTwinMotion(printerId: number) {
  listeners.get(printerId)?.forEach((listener) => listener.reset());
}

export function anchorTwinMotion(printerId: number, position: Position) {
  listeners.get(printerId)?.forEach((listener) => listener.anchor(position));
}

export function hasTwinMovementControls(model: string | null | undefined) {
  return isTwinEnabled() && isTwinModel(model);
}

export function twinMotionStatus(
  msg: { conn?: { mqtt?: boolean }; age?: number | null; s?: { home_flag?: number; gcode_state?: string; stg_cur?: number } } | null,
  elapsed: number,
) {
  const fresh = msg?.conn?.mqtt === true && typeof msg.age === 'number' && msg.age + elapsed <= 15;
  const axes = typeof msg?.s?.home_flag === 'number' ? msg.s.home_flag & 7 : null;
  const stageHoming = msg?.s?.stg_cur === 13;
  const printState = msg?.s?.gcode_state ?? '';
  return {
    idle: fresh && IDLE_PRINTER_STATES.includes(printState),
    homed: fresh && axes === 7 && !stageHoming,
    trackingPrint: fresh && ACTIVE_PRINT_STATES.includes(printState),
  };
}

export function createManualMotion() {
  let estimate: { target: Position; moves: number } | null = null;
  let reference: Position | null = null;
  function reset() {
    estimate = null;
    reference = null;
  }
  return {
    get target() { return estimate?.target ?? reference; },
    get referenced() { return reference !== null; },
    reset,
    anchor(position: Position) {
      estimate = null;
      reference = { ...position };
    },
    observe(status: ReturnType<typeof twinMotionStatus>) {
      if (!status.idle || !status.homed) reset();
    },
    jog(delta: Position) {
      if (!reference) return;
      const current = estimate ?? { target: { ...reference }, moves: 0 };
      estimate = current;
      current.moves++;
      current.target.x += delta.x;
      current.target.y += delta.y;
      current.target.z += delta.z;
      return () => {
        // A late failure from before homing, disconnection or a print belongs to the discarded estimate.
        if (estimate !== current) return;
        current.target.x -= delta.x;
        current.target.y -= delta.y;
        current.target.z -= delta.z;
        if (--current.moves === 0) estimate = null;
      };
    },
  };
}
