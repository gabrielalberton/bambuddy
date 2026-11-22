import { ACTIVE_PRINT_STATES, IDLE_PRINTER_STATES } from '../../utils/printer';
import { isTwinEnabled, isTwinModel } from './twinFlags';

type Position = { x: number; y: number; z: number };

// After a full G28 the A1 is near the center of the plate with the nozzle slightly raised.
// This visual reference comes from the camera after homing. The firmware reports no XYZ.
const A1_HOME_POSE: Readonly<Position> = { x: 128, y: 128, z: 5 };
type Jog = (delta: Position) => (() => void) | undefined;
type Listener = { jog: Jog; reset: () => void };

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
    homeInProgress: fresh && (stageHoming || (axes !== null && axes !== 7)),
    trackingPrint: fresh && ACTIVE_PRINT_STATES.includes(printState),
  };
}

export function createManualMotion() {
  let estimate: { target: Position; moves: number } | null = null;
  let observedUnhomed = false;
  let referenced = false;
  function reset() {
    estimate = null;
    observedUnhomed = false;
    referenced = false;
  }
  return {
    get target() { return referenced ? estimate?.target ?? A1_HOME_POSE : null; },
    get referenced() { return referenced; },
    reset,
    observe(status: ReturnType<typeof twinMotionStatus>) {
      if (!status.idle) {
        reset();
      } else if (status.homeInProgress) {
        estimate = null;
        observedUnhomed = true;
        referenced = false;
      } else if (status.homed && observedUnhomed) {
        observedUnhomed = false;
        referenced = true;
      } else if (!status.homed) {
        reset();
      }
    },
    jog(delta: Position) {
      if (!referenced) return;
      const current = estimate ?? { target: { ...A1_HOME_POSE }, moves: 0 };
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
