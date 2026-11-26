import type { MountInfo, Pen, PenTypeInfo, Settings } from './api';
import { PenTypeSelect } from './Controls';
import { mountOf, selectMount } from './mounts';
import { mm } from './thickness';

const ZSWEEP_STEPS = [
  'Plote o teste. Cada linha horizontal começa apertada (Z 5) e termina com o bico no ar (Z 8); só elas são o teste.',
  'As verticais, a régua e os números são só marcação: cada número é o Z do bico naquele ponto.',
  'Veja em que número o traço começa a afinar e em que número ele some, e me informe os dois.',
];

/** Teste de altura: suporte e tipo de caneta, o que o teste faz e o botão que gera e valida o plano. */
export function ZSweepTest({
  settings, mounts, penTypes, disabled, canEdit, canGenerate, hint, onSettings, onPen, onGenerate,
}: {
  settings: Settings; mounts: MountInfo[]; penTypes: PenTypeInfo[]; disabled?: boolean; canEdit: boolean;
  canGenerate: boolean; hint?: string; onSettings: (next: Settings) => void; onPen: (pen: Pen) => void;
  onGenerate: () => void;
}) {
  const pen = settings.pens[settings.active_pen];
  const mount = mountOf(pen);
  const type = penTypes.find(item => item.key === pen.pen_type);
  return <div className="plotter-tests">
    <h3>Teste de altura (Z)</h3>
    <div className="plotter-segments" role="group" aria-label="Suporte no teste">
      {mounts.map(item => <button key={item.key} type="button" aria-pressed={mount === item.key} disabled={disabled}
        onClick={() => onSettings(selectMount(settings, item, penTypes))}>{item.name}</button>)}
    </div>
    <div className="plotter-fields"><PenTypeSelect pen={pen} types={penTypes} disabled={disabled || !canEdit} onChange={onPen} /></div>
    {type && <p className="plotter-muted">{type.about} Valores iniciais: aperto de {mm(pen.depth_min)} a {mm(pen.depth_max)} mm,
      traço de ~{mm(pen.line_width)} mm.</p>}
    <ol className="plotter-steps">{ZSWEEP_STEPS.map(step => <li key={step}>{step}</li>)}</ol>
    <button type="button" disabled={disabled || !canGenerate} onClick={onGenerate}>Gerar e validar o teste</button>
    {hint && <p className="plotter-muted">{hint}</p>}
  </div>;
}
