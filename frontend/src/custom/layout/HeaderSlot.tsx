import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import './headerSlot.css';
import { headerStatusEnabled } from './headerFlags';

/**
 * Espaço do logo no cabeçalho compacto (celular). Um componente da página pode "subir" para cá com <InHeader>:
 * enquanto ele estiver montado o logo some e o conteúdo dele aparece no lugar. Modo impressora única: o bloco de
 * status do card (estado, placa, trabalho, progresso, último) vira o cabeçalho.
 */
let slot: HTMLElement | null = null;
let users = 0;
const listeners = new Set<() => void>();
let version = 0;
const emit = () => {
  version += 1;
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const useVersion = () => useSyncExternalStore(subscribe, () => version);


export function HeaderSlot({ children }: { children: ReactNode }) {
  useVersion();
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    slot = el;
    emit();
    return () => {
      if (slot === el) slot = null;
      emit();
    };
  }, [el]);
  const occupied = users > 0;
  return (
    <>
      {!occupied && children}
      <div ref={setEl} data-custom-header-status="" className={occupied ? 'ml-2 mr-1 min-w-0 flex-1' : 'hidden'} />
    </>
  );
}

/** Renderiza `children` no cabeçalho quando `enabled` e o espaço existe; senão, no lugar normal. */
export function InHeader({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  useVersion();
  const on = enabled && headerStatusEnabled();
  useEffect(() => {
    if (!on) return;
    users += 1;
    emit();
    return () => {
      users -= 1;
      emit();
    };
  }, [on]);
  if (on && slot) return createPortal(children, slot);
  return <>{children}</>;
}
