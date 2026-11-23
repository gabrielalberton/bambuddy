import { useEffect, useState, type RefObject } from 'react';
import { ScanLine } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { api, withStreamToken } from '../../api/client';
import type { TwinHandle } from './engine/engine';
import { useTwinStrings } from './i18n';

type Pose = NonNullable<ReturnType<TwinHandle['getIdlePose']>>;
type Result = 'unknown' | 'visually_close' | 'divergent';

function samePose(a: Pose, b: Pose | null) {
  return b && Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.z - b.z)) <= 2;
}

export function VisualCheck({ printerId, twin }: { printerId: number; twin: RefObject<TwinHandle | null> }) {
  const endpoint = `/api/v1/custom/twin/stream/${printerId}/visual-check`;
  const s = useTwinStrings();
  const { authEnabled, user, hasPermission } = useAuth();
  const { data: stream } = useQuery({
    queryKey: ['camera-stream-token', user?.id ?? null],
    queryFn: api.getCameraStreamToken,
    enabled: authEnabled && !!user && hasPermission('camera:view'),
    staleTime: 50 * 60 * 1000,
  });
  const token = stream?.token;
  const [available, setAvailable] = useState(false);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<{ comparison: Result; pose: Pose | null } | null>(null);

  useEffect(() => {
    if (authEnabled && !token) return;
    const controller = new AbortController();
    const url = token ? `${endpoint}?token=${encodeURIComponent(token)}` : endpoint;
    fetch(url, { signal: controller.signal, cache: 'no-store' })
      .then(response => setAvailable(response.ok))
      .catch(() => {});
    return () => controller.abort();
  }, [authEnabled, endpoint, token]);

  useEffect(() => {
    if (!result) return;
    const interval = window.setInterval(() => {
      if (result.pose && !samePose(result.pose, twin.current?.getIdlePose() ?? null)) setResult(null);
    }, 250);
    const timeout = window.setTimeout(() => setResult(null), 7000);
    return () => { window.clearInterval(interval); window.clearTimeout(timeout); };
  }, [result, twin]);

  async function compare() {
    const pose = twin.current?.getIdlePose() ?? null;
    if (!pose) {
      setResult({ comparison: 'unknown', pose: null });
      return;
    }
    setChecking(true);
    setResult(null);
    let comparison: Result = 'unknown';
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const query = `x=${pose.x}&y=${pose.y}&z=${pose.z}`;
      const url = token ? `${endpoint}?${query}&token=${encodeURIComponent(token)}` : withStreamToken(`${endpoint}?${query}`);
      const response = await fetch(url, {
        cache: 'no-store',
        signal: controller.signal,
      });
      if (response.ok && samePose(pose, twin.current?.getIdlePose() ?? null)) {
        const body = await response.json();
        if (body.comparison === 'divergent' || body.comparison === 'visually_close') comparison = body.comparison;
      }
    } catch { /* Sem quadros da câmera, o resultado é inconclusivo. */ }
    finally { window.clearTimeout(timeout); }
    setResult({ comparison, pose: comparison === 'unknown' ? null : pose });
    setChecking(false);
  }

  if (!available) return null;
  return (
    <div className="custom-twin-visual-check absolute top-1 right-1 z-[21] flex max-w-[calc(100%-0.5rem)] flex-col items-end gap-1">
      <button
        type="button"
        title={s.compareCamera}
        aria-label={s.compareCamera}
        disabled={checking}
        onClick={event => { event.stopPropagation(); void compare(); }}
        className="grid h-[44px] w-[44px] place-items-center rounded-lg bg-black/70 text-white disabled:opacity-60"
      >
        <ScanLine className="h-5 w-5" aria-hidden="true" />
      </button>
      {checking || result ? (
        <span role="status" className={`rounded px-2 py-1 text-xs text-white ${result?.comparison === 'divergent' ? 'bg-red-800' : 'bg-black/70'}`}>
          {checking ? s.comparingCamera : s.visualResult[result?.comparison ?? 'unknown']}
        </span>
      ) : null}
    </div>
  );
}
