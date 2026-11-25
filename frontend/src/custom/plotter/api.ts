import { ApiError, getAuthToken } from '../../api/client';

export type Paper = { x: number; y: number; w: number; h: number; margin: number; thickness: number };
export type Placement = { cx: number; cy: number; width: number; rotation: number };
export type Rect = [number, number, number, number];
export type Machine = { plate_w: number; plate_h: number; nozzle_x: [number, number]; nozzle_y: [number, number] };
export type Pen = {
  name: string; offset_x: number; offset_y: number; z_contact: number | null;
  lift: number; depth_min: number; depth_max: number; max_compression: number;
  line_width: number; draw_speed: number; travel_speed: number; z_speed: number;
  dwell_ms: number; use_mesh: boolean; table: [number, number][];
};
export type Settings = {
  machine: Machine; pens: Record<string, Pen>; active_pen: string;
  paper: Paper; placement: Placement | null;
};
export type Drawing = {
  id: string; width: number; height: number; strokes: { p: number[]; c: number }[];
  meta: { name: string; threshold: number };
};
type Notice = { code: string; text: string };
export type Jog = { z: number; floor: number; max: number; settling: number };
export type Status = {
  connected: boolean; state: string; plotting: boolean; progress: number | null;
  blockers: Notice[]; jog: Jog | null;
};
export type Config = {
  paper_presets: { id: string; w: number; h: number }[];
  max_upload_mb: number;
  limits: { jog_max_step: number };
  printers: { id: number; name: string; supported: boolean; plate_vision?: boolean }[];
};
export type PlateMatch = {
  found: boolean; reason?: 'camera_alignment'; image: string; received_at: number;
  corners?: [number, number][]; front_plane_mm?: number; y_mm?: number;
};
export type Kind = 'drawing' | 'ladder' | 'cross' | 'frame';
export type SimPoint = [x: number, y: number, depth: number, time: number];
export type Plan = {
  id: string; title: string; kind: Kind; ok: boolean;
  errors: Notice[]; warnings: Notice[]; sim: SimPoint[];
  stats: { time_s?: number }; calibration: { rows?: { depth: number; y: number }[]; target?: [number, number] };
};

async function request(path: string, method = 'GET', body?: unknown) {
  const headers = new Headers();
  const token = getAuthToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (body !== undefined && !(body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api/v1/custom/plotter${path}`, {
    method, headers, body: body instanceof FormData ? body : JSON.stringify(body),
  });
  if (response.ok) return response;
  const result = await response.json().catch(() => ({}));
  const detail = result.detail;
  const message = detail?.message || (typeof detail === 'string' ? detail : `Erro HTTP ${response.status}`);
  throw new ApiError(message, response.status, null, detail);
}

async function json<T>(path: string, method?: string, body?: unknown): Promise<T> {
  return (await request(path, method, body)).json();
}

const printer = (id: number) => `/printers/${id}`;
const planPath = (id: number, plan: Plan) => `${printer(id)}/plans/${plan.id}`;

export const plotter = {
  config: () => json<Config>('/config'),
  settings: (id: number) => json<Settings>(`${printer(id)}/settings`),
  save: (id: number, settings: Settings) => json<Settings>(`${printer(id)}/settings`, 'PUT', settings),
  plateCamera: (id: number) => json<PlateMatch>(`${printer(id)}/plate-camera`),
  status: (id: number) => json<Status>(`${printer(id)}/status`),
  drawing: (file: File, options: object) => {
    const body = new FormData();
    body.append('file', file);
    body.append('options', JSON.stringify(options));
    return json<Drawing>('/drawings', 'POST', body);
  },
  revectorize: (drawing: Drawing, options: object) =>
    json<Drawing>(`/drawings/${drawing.id}/vectorize`, 'POST', { options }),
  image: async (drawing: Drawing) => (await request(`/drawings/${drawing.id}/image`)).blob(),
  plan: (id: number, body: object) => json<Plan>(`${printer(id)}/plans`, 'POST', body),
  download: async (id: number, plan: Plan) => (await request(`${planPath(id, plan)}/download`)).blob(),
  start: (id: number, plan: Plan) => json<{ started: boolean }>(`${planPath(id, plan)}/start`, 'POST'),
  jogStart: (id: number, penId: string) => json<Jog>(`${printer(id)}/jog/start`, 'POST', { pen_id: penId }),
  jogMove: (id: number, z: number) => json<Jog>(`${printer(id)}/jog/move`, 'POST', { z }),
  jogFinish: (id: number, save: boolean) => json<unknown>(`${printer(id)}/jog/finish`, 'POST', { save }),
};

export function drawableArea(machine: Machine, pen: Pen, paper: Paper): Rect | null {
  const { x, y, w, h, margin } = paper;
  const rect: Rect = [
    Math.max(x + margin, 0, machine.nozzle_x[0] + pen.offset_x),
    Math.max(y + margin, 0, machine.nozzle_y[0] + pen.offset_y),
    Math.min(x + w - margin, machine.plate_w, machine.nozzle_x[1] + pen.offset_x),
    Math.min(y + h - margin, machine.plate_h, machine.nozzle_y[1] + pen.offset_y),
  ];
  return rect[2] > rect[0] && rect[3] > rect[1] ? rect : null;
}
