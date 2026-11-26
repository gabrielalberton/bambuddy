import { Check } from 'lucide-react';

/** Atalho da confirmação de "mesa liberada" do trabalho anterior, que bloqueia a próxima plotagem. */
export function PlateClear({ needed, allowed, onConfirm }: { needed: boolean; allowed: boolean; onConfirm: () => void }) {
  if (!needed) return null;
  return <div className="plotter-plate-clear" role="group" aria-label="Mesa liberada">
    <p className="plotter-muted">
      O trabalho anterior terminou e o Bambuddy espera a confirmação de mesa liberada. Tire a folha e confirme para poder iniciar a plotagem.
    </p>
    <button type="button" disabled={!allowed} onClick={onConfirm}><Check size={17} aria-hidden="true" /> Mesa liberada</button>
    {!allowed && <p className="plotter-muted">Seu usuário não tem permissão para confirmar a mesa liberada.</p>}
  </div>;
}
