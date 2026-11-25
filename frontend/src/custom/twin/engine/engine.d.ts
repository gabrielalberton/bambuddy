// Tipos do motor do gêmeo digital (engine.js é o porte em JS puro do twin avulso; ver custom/docs/gemeo-digital.md).
export interface TwinTuning {
  /** avanço em segundos de programa (-5..5) */
  lead?: number;
  lat?: number;
  tau?: number;
  /** aproxima a câmera do objeto durante a impressão (desligado: enquadramento fixo) */
  autoFocus?: boolean;
}

export type MotionStatus = 'unknown' | 'estimated' | 'print' | 'camera';

export interface TwinOptions {
  printerId?: number;
  onMotionStatus?: (status: MotionStatus) => void;
  /** URL do SSE de estado (chamada a cada (re)conexão: deve trazer o token de stream atual) */
  eventsUrl: () => string;
  /** URL do pacote do job */
  jobUrl: (id: string) => string;
  /** URL do GLB opcional da A1 (404 = modelo procedural) */
  modelUrl?: (() => string) | null;
  tuning?: TwinTuning;
  /** expõe `window.__twin` (testes) */
  debug?: boolean;
  /** força o modelo procedural */
  procedural?: boolean;
}

export interface TwinStats {
  fps: number;
  frames: number;
  model: 'procedural' | 'step';
  paused: boolean;
  sse: 'connecting' | 'open' | 'closed';
}

export interface TwinHandle {
  stats: TwinStats;
  dispose(): void;
  debug: unknown;
}

export function createTwin(container: HTMLElement, opts: TwinOptions): TwinHandle;
