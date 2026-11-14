import { getAuthToken } from '../../api/client';

const BASE = '/api/v1/custom/webpush';

export class WebPushApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${BASE}${path}`, { ...init, headers, cache: 'no-store', credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new WebPushApiError(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export interface WebPushDevice {
  id: number;
  service: string;
  user_agent: string | null;
  created_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  this_device: boolean;
}

export interface WebPushTestResult {
  sent: number;
  failed: number;
  removed: number;
  errors: string[];
}

export const webPushApi = {
  publicKey: () => call<{ public_key: string }>('/public-key'),
  subscribe: (sub: PushSubscriptionJSON) =>
    call<{ id: number; created: boolean }>('/subscribe', { method: 'POST', body: JSON.stringify(sub) }),
  unsubscribe: (endpoint: string) =>
    call<{ deleted: number }>('/subscribe', { method: 'DELETE', body: JSON.stringify({ endpoint }) }),
  devices: (endpoint?: string) =>
    call<WebPushDevice[]>(`/devices${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ''}`),
  test: (endpoint?: string) =>
    call<WebPushTestResult>('/test', { method: 'POST', body: JSON.stringify(endpoint ? { endpoint } : {}) }),
};
