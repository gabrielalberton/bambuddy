import { useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { isTwinEnabled, isTwinModel } from './twinFlags';

export type TwinViewMode = 'camera' | 'twin';

/** Última escolha da chave, por navegador (todas as telas de câmera compartilham). */
export const TWIN_VIEW_STORAGE_KEY = 'custom.twin.view';

const listeners = new Set<() => void>();
let current: TwinViewMode | null = null;

function read(): TwinViewMode {
  if (current) return current;
  try {
    current = localStorage.getItem(TWIN_VIEW_STORAGE_KEY) === 'twin' ? 'twin' : 'camera';
  } catch {
    current = 'camera';
  }
  return current;
}

export function setTwinViewMode(mode: TwinViewMode): void {
  current = mode;
  try {
    localStorage.setItem(TWIN_VIEW_STORAGE_KEY, mode);
  } catch {
    /* sem localStorage: vale só nesta sessão */
  }
  listeners.forEach((l) => l());
}

/** Só para testes: esquece o valor em memória. */
export function resetTwinViewModeCache(): void {
  current = null;
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === TWIN_VIEW_STORAGE_KEY) {
      current = null;
      cb();
    }
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener('storage', onStorage);
  };
}

export function useTwinViewMode(): [TwinViewMode, (m: TwinViewMode) => void] {
  const mode = useSyncExternalStore(subscribe, read, () => 'camera' as TwinViewMode);
  return [mode, setTwinViewMode];
}

/** O twin pode ser oferecido para esta impressora? (interruptor ligado + modelo A1). */
export function useTwinAvailable(printerId: number): boolean {
  const enabled = isTwinEnabled() && printerId > 0;
  const { data: printers } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters, enabled, staleTime: 60_000 });
  if (!enabled) return false;
  const p = printers?.find((x) => x.id === printerId);
  return isTwinModel(p?.model);
}

/** Twin visível agora no lugar da câmera (para o visualizador pausar a detecção de travamento do stream). */
export function useTwinActive(printerId: number): boolean {
  const available = useTwinAvailable(printerId);
  const [mode] = useTwinViewMode();
  return available && mode === 'twin';
}
