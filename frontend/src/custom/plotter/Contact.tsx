import { useState } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type { Jog } from './api';
import { mm } from './thickness';

const round2 = (value: number) => Math.round(value * 100) / 100;

/**
 * Altura de contato em poucos toques: um botão faz o homing e leva a caneta, alta, para o centro do papel;
 * Descer/Subir com o passo escolhido; OK grava o contato.
 */
export function ContactAdjust({
  jog, contact, steps, hint, canControl, canStart, reason, onStart, onMove, onFinish,
}: {
  jog?: Jog | null; contact: number | null; steps: number[]; hint: string; canControl: boolean; canStart: boolean;
  reason?: string; onStart: () => void; onMove: (z: number) => void; onFinish: (save: boolean) => void;
}) {
  const sizes = [...new Set(steps.filter(step => step > 0))].sort((a, b) => b - a);
  const [picked, setPicked] = useState<number>();
  const [confirmed, setConfirmed] = useState(false);
  const step = picked !== undefined && sizes.includes(picked) ? picked : (sizes[0] ?? 1);

  if (!jog) {
    return <div className="plotter-contact">
      <h3>Altura de contato</h3>
      <p className="plotter-muted">
        {contact === null ? 'Ainda não calibrada.' : `Salva: bico em Z ${mm(contact)} mm.`} O botão faz o homing
        (o bico toca a frente da mesa e a caneta fica para fora) e leva a caneta, alta, para o centro do papel,
        com o bico a 20 mm.
      </p>
      <label className="plotter-check">
        <input type="checkbox" checked={confirmed} disabled={!canControl} onChange={e => setConfirmed(e.target.checked)} />
        Estou junto à A1, com o papel no lugar e o trajeto livre.
      </label>
      <button type="button" className="plotter-primary" disabled={!canControl || !canStart || !confirmed}
        onClick={() => { setConfirmed(false); onStart(); }}>Fazer homing e levar a caneta ao centro</button>
      {reason && <p className="plotter-muted">{reason}</p>}
    </div>;
  }

  const moving = !canControl || jog.settling > 0;
  return <div className="plotter-contact">
    <h3>Altura de contato</h3>
    <p role="status" className="plotter-jog-z">Bico em Z {jog.z.toFixed(2).replace('.', ',')} mm
      {jog.settling > 0 && <small> · aguarde o movimento</small>}</p>
    <p className="plotter-muted">{hint} Depois toque em OK.</p>
    <div className="plotter-segments" role="group" aria-label="Passo">
      {sizes.map(size => <button key={size} type="button" aria-pressed={size === step} onClick={() => setPicked(size)}>
        {mm(size)} mm</button>)}
    </div>
    <div className="plotter-jog">
      <button type="button" disabled={moving || jog.z - step < jog.floor - 1e-9} onClick={() => onMove(round2(jog.z - step))}>
        <ArrowDown size={20} aria-hidden="true" /> Descer {mm(step)}</button>
      <button type="button" disabled={moving || jog.z + step > jog.max + 1e-9} onClick={() => onMove(round2(jog.z + step))}>
        <ArrowUp size={20} aria-hidden="true" /> Subir {mm(step)}</button>
    </div>
    <button type="button" className="plotter-primary" disabled={moving} onClick={() => onFinish(true)}>OK, salvar contato e levantar</button>
    <button type="button" className="plotter-contact-cancel" disabled={moving} onClick={() => onFinish(false)}>Cancelar e levantar sem salvar</button>
  </div>;
}
