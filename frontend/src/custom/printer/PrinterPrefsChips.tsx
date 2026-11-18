import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleDot, Gauge } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getAuthToken } from '../../api/client';

/**
 * custom(printer-prefs): no card compacto, bico configurado e modo de velocidade sempre visíveis e trocáveis.
 *  - Bico: só 0.2 e 0.4 (os que o Gabriel tem). A A1 não tem sensor; o backend manda `set_accessories`.
 *    Bloqueado durante a impressão.
 *  - Velocidade: imprimindo, troca já; parada, vira o padrão da próxima impressão (aplicado a partir da camada 2).
 */

interface Prefs {
  default_speed: number | null;
  speed_level: number | null;
  nozzle_diameter: string;
  nozzle_options: string[];
  apply_from_layer: number;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/v1/custom/printers${path}`, { ...init, headers, cache: 'no-store', credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const printerPrefsApi = {
  get: (id: number) => call<Prefs>(`/${id}/prefs`),
  setSpeed: (id: number, mode: number) => call<{ applied_now: boolean }>(`/${id}/speed?mode=${mode}`, { method: 'PUT' }),
  setNozzle: (id: number, diameter: string) => call<{ nozzle_diameter: string }>(`/${id}/nozzle?diameter=${diameter}`, { method: 'POST' }),
};

const SPEED_KEYS: Record<number, string> = { 1: 'silent', 2: 'standard', 3: 'sport', 4: 'ludicrous' };

function norm(d: string | number | null | undefined): string {
  const n = Number(d);
  return Number.isFinite(n) && n > 0 ? n.toFixed(1) : '';
}

const chip = 'flex h-8 items-center gap-1 px-2.5 rounded-lg text-xs transition-opacity hover:opacity-80 disabled:opacity-50';

export function PrinterPrefsChips({
  printerId,
  isPrinting,
  speedLevel,
  nozzleDiameter,
  canControl,
  onToast,
}: {
  printerId: number;
  isPrinting: boolean;
  speedLevel: number | null | undefined;
  nozzleDiameter: string | number | null | undefined;
  canControl: boolean;
  onToast?: (message: string, type?: 'success' | 'error') => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState<'nozzle' | 'speed' | null>(null);
  const key = ['customPrinterPrefs', printerId];
  const { data } = useQuery({ queryKey: key, queryFn: () => printerPrefsApi.get(printerId), refetchInterval: 30_000 });

  const speedMut = useMutation({
    mutationFn: (mode: number) => printerPrefsApi.setSpeed(printerId, mode),
    onSuccess: (res, mode) => {
      qc.setQueryData(key, (old: Prefs | undefined) => (old ? { ...old, default_speed: mode } : old));
      qc.invalidateQueries({ queryKey: ['printerStatus', printerId] });
      onToast?.(
        res.applied_now
          ? t('custom.prefs.speedNow', { mode: t(`printers.speed.${SPEED_KEYS[mode]}`) })
          : t('custom.prefs.speedNext', { mode: t(`printers.speed.${SPEED_KEYS[mode]}`) }),
        'success',
      );
    },
    onError: (e: Error) => onToast?.(e.message, 'error'),
  });
  const nozzleMut = useMutation({
    mutationFn: (d: string) => printerPrefsApi.setNozzle(printerId, d),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ['printerStatus', printerId] });
      onToast?.(t('custom.prefs.nozzleSet', { d: res.nozzle_diameter }), 'success');
    },
    onError: (e: Error) => onToast?.(e.message, 'error'),
  });

  const nozzle = norm(nozzleDiameter) || norm(data?.nozzle_diameter);
  const options = data?.nozzle_options ?? ['0.2', '0.4'];
  // Imprimindo, mostra o modo real; parada, o padrão que vai valer na próxima.
  const shownSpeed = isPrinting ? speedLevel ?? data?.speed_level : data?.default_speed ?? speedLevel ?? data?.speed_level;
  const speedLabel = shownSpeed && SPEED_KEYS[shownSpeed] ? t(`printers.speed.${SPEED_KEYS[shownSpeed]}`) : '—';

  return (
    <>
      <div className="relative">
        <button
          data-testid="custom-nozzle-chip"
          className={`${chip} bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400`}
          onClick={() => setOpen(open === 'nozzle' ? null : 'nozzle')}
          disabled={!canControl}
          title={isPrinting ? t('custom.prefs.nozzleBusy') : t('custom.prefs.nozzleTitle')}
        >
          <CircleDot className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
          {nozzle ? `${nozzle} mm` : '—'}
        </button>
        {open === 'nozzle' && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(null)} />
            <div className="absolute bottom-full left-0 mb-1 z-50 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg py-1 min-w-[150px]">
              <p className="px-3 py-1 text-[11px] text-bambu-gray">
                {isPrinting ? t('custom.prefs.nozzleBusy') : t('custom.prefs.nozzleHint')}
              </p>
              {options.map((d) => (
                <button
                  key={d}
                  disabled={isPrinting || nozzleMut.isPending}
                  onClick={() => {
                    setOpen(null);
                    if (norm(d) !== nozzle) nozzleMut.mutate(d);
                  }}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
                    norm(d) === nozzle ? 'text-bambu-green bg-bambu-green/10' : 'text-white hover:bg-bambu-dark-tertiary'
                  }`}
                >
                  {d} mm
                </button>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="relative">
        <button
          data-testid="custom-speed-chip"
          className={`${chip} bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-400`}
          onClick={() => setOpen(open === 'speed' ? null : 'speed')}
          disabled={!canControl}
          title={isPrinting ? t('printers.speed.title') : t('custom.prefs.speedDefaultTitle')}
        >
          <Gauge className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
          {speedLabel}
        </button>
        {open === 'speed' && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(null)} />
            <div className="absolute bottom-full right-0 mb-1 z-50 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg py-1 min-w-[170px]">
              <p className="px-3 py-1 text-[11px] text-bambu-gray">
                {isPrinting ? t('custom.prefs.speedNowHint') : t('custom.prefs.speedNextHint', { layer: data?.apply_from_layer ?? 2 })}
              </p>
              {[1, 2, 3, 4].map((mode) => (
                <button
                  key={mode}
                  disabled={speedMut.isPending}
                  onClick={() => {
                    setOpen(null);
                    speedMut.mutate(mode);
                  }}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                    shownSpeed === mode ? 'text-bambu-green bg-bambu-green/10' : 'text-white hover:bg-bambu-dark-tertiary'
                  }`}
                >
                  {t(`printers.speed.${SPEED_KEYS[mode]}`)}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
