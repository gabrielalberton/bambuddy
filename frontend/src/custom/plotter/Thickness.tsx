import { useState, type ReactNode } from 'react';
import type { Calibration, Kind, MountInfo, Pen, PenTypeInfo, Settings, TestLayouts } from './api';
import { Numeric, PenTypeSelect } from './Controls';
import { mountOf, selectMount } from './mounts';
import {
  TEST_INFO, TEST_KINDS, combResult, isTest, ladderResult, mm, testDepths, waveResult, wedgeDepth, wedgeResult,
  type TestKind,
} from './thickness';

type Apply = (pen: Pen, notes: string[]) => void;
type Outcome = { pen: Pen; notes: string[] } | { error: string };

/** Botão "Gravar na caneta" com a mensagem de erro do cálculo, comum aos quatro formulários. */
function Save({ disabled, compute, onApply, children }: {
  disabled?: boolean; compute: () => Outcome; onApply: Apply; children: ReactNode;
}) {
  const [error, setError] = useState('');
  return <>
    {children}
    {error && <p className="plotter-error" role="alert">{error}</p>}
    <button type="button" disabled={disabled} onClick={() => {
      const result = compute();
      if ('error' in result) setError(result.error);
      else { setError(''); onApply(result.pen, result.notes); }
    }}>Gravar resultado na caneta</button>
  </>;
}

function LadderForm({ pen, depths, disabled, onApply }: { pen: Pen; depths: number[]; disabled?: boolean; onApply: Apply }) {
  const [widths, setWidths] = useState<(number | null)[]>(() => depths.map(() => null));
  const [best, setBest] = useState<number | null>(null);
  return <Save disabled={disabled} onApply={onApply} compute={() => ladderResult(pen, depths, widths, best)}>
    <p className="plotter-muted">Largura de cada linha em mm; em branco se não marcou.</p>
    <div className="plotter-fields">
      {depths.map((depth, index) => <Numeric key={depth} label={`Linha ${mm(depth)} mm`} value={widths[index]} min={0} max={20} nullable
        onChange={value => setWidths(widths.map((width, i) => i === index ? value : width))} />)}
    </div>
    <label className="plotter-field"><span>Maior aperto com traço bom</span>
      <select aria-label="Maior aperto com traço bom" value={best ?? ''} onChange={e => setBest(e.target.value === '' ? null : Number(e.target.value))}>
        <option value="">A última linha medida</option>
        {depths.map(depth => <option key={depth} value={depth}>{mm(depth)} mm</option>)}
      </select>
    </label>
  </Save>;
}

function CombForm({ pen, depths, spacings, disabled, onApply }: {
  pen: Pen; depths: number[]; spacings: number[]; disabled?: boolean; onApply: Apply;
}) {
  const [closed, setClosed] = useState<(number | null)[]>(() => depths.map(() => null));
  return <Save disabled={disabled} onApply={onApply} compute={() => combResult(pen, depths, spacings, closed)}>
    <p className="plotter-muted">Em cada fileira, a última célula que virou mancha cheia (espaçamento escrito em cima da coluna).</p>
    <div className="plotter-fields">
      {depths.map((depth, index) => <label key={depth} className="plotter-field"><span>Fileira {mm(depth)} mm</span>
        <select aria-label={`Última célula fechada em ${mm(depth)} mm`} value={closed[index] ?? ''}
          onChange={e => setClosed(closed.map((cell, i) => i === index ? (e.target.value === '' ? null : Number(e.target.value)) : cell))}>
          <option value="">Não medi</option>
          <option value={-1}>Nenhuma fechou</option>
          {spacings.map((spacing, cell) => <option key={spacing} value={cell}>{mm(spacing)} mm</option>)}
        </select>
      </label>)}
    </div>
  </Save>;
}

function WedgeForm({ pen, layout, disabled, onApply }: {
  pen: Pen; layout: { from: number; to: number; length: number }; disabled?: boolean; onApply: Apply;
}) {
  const [forward, setForward] = useState<number | null>(null);
  const [back, setBack] = useState<number | null>(null);
  const [tooWide, setTooWide] = useState<number | null>(null);
  const marks = Math.round(layout.length / 10);
  const depth = (mark: number | null) => mark === null ? '' : ` · ${mm(Math.round(wedgeDepth(layout, mark) * 1000) / 1000)} mm`;
  return <Save disabled={disabled} onApply={onApply} compute={() => wedgeResult(pen, layout, forward, back, tooWide)}>
    <p className="plotter-muted">Número da grade (0 a {marks}); a régua vai de 0 a {mm(layout.to)} mm de aperto.</p>
    <div className="plotter-fields">
      <Numeric label={`Ida (→) começou a marcar${depth(forward)}`} value={forward} min={0} max={marks} nullable onChange={setForward} />
      <Numeric label={`Volta (←) parou de marcar${depth(back)}`} value={back} min={0} max={marks} nullable onChange={setBack} />
      <Numeric label={`Passou do ponto (opcional)${depth(tooWide)}`} value={tooWide} min={0} max={marks} nullable onChange={setTooWide} />
    </div>
  </Save>;
}

function WaveForm({ pen, peak, ramps, disabled, onApply }: {
  pen: Pen; peak: number; ramps: number[]; disabled?: boolean; onApply: Apply;
}) {
  const [ramp, setRamp] = useState(ramps.at(-1) ?? 40);
  const [entry, setEntry] = useState<number | null>(null);
  const [exit, setExit] = useState<number | null>(null);
  return <Save disabled={disabled} onApply={onApply} compute={() => waveResult(pen, peak, ramp, entry, exit)}>
    <p className="plotter-muted">Na ponta escolhida, a quantos mm da ponta o traço sumiu (use a grade de 10 mm).</p>
    <div className="plotter-fields">
      <label className="plotter-field"><span>Ponta medida</span>
        <select aria-label="Ponta medida" value={ramp} onChange={e => setRamp(Number(e.target.value))}>
          {ramps.map(value => <option key={value} value={value}>Rampa de {mm(value)} mm</option>)}
        </select>
      </label>
      <Numeric label="Entrada (esquerda), mm" value={entry} min={0} max={ramp} nullable onChange={setEntry} />
      <Numeric label="Saída (direita), mm" value={exit} min={0} max={ramp} nullable onChange={setExit} />
    </div>
  </Save>;
}

function ResultForm({ test, pen, layouts, calibration, disabled, onApply }: {
  test: TestKind; pen: Pen; layouts?: TestLayouts; calibration?: Calibration; disabled?: boolean; onApply: Apply;
}) {
  const same = calibration?.test === test ? calibration : undefined;
  if (test === 'ladder' || test === 'comb') {
    const depths = testDepths(test, layouts, same);
    if (!depths.length) return null;
    if (test === 'ladder') return <LadderForm key={depths.join()} pen={pen} depths={depths} disabled={disabled} onApply={onApply} />;
    const spacings = same?.spacings ?? layouts?.comb.spacings ?? [];
    return <CombForm key={depths.join() + spacings.join()} pen={pen} depths={depths} spacings={spacings} disabled={disabled} onApply={onApply} />;
  }
  if (test === 'wedge') {
    const layout = same?.to !== undefined && same.length
      ? { from: same.from ?? 0, to: same.to, length: same.length } : layouts?.wedge;
    if (!layout) return null;
    return <WedgeForm key={`${layout.to}-${layout.length}`} pen={pen} layout={layout} disabled={disabled} onApply={onApply} />;
  }
  const ramps = same?.tapers?.map(taper => taper.ramp) ?? layouts?.wave.ramps ?? [];
  const peak = same?.to ?? layouts?.wave.to ?? pen.depth_max;
  if (!ramps.length) return null;
  return <WaveForm key={`${peak}-${ramps.join()}`} pen={pen} peak={peak} ramps={ramps} disabled={disabled} onApply={onApply} />;
}

/** Testes de espessura no cartão de envio: suporte e tipo de caneta, o padrão a plotar e o resultado medido. */
export function ThicknessTests({
  settings, mounts, penTypes, layouts, kind, calibration, disabled, canEdit, canGenerate, hint,
  onSettings, onPen, onPick, onGenerate, onApply,
}: {
  settings: Settings; mounts: MountInfo[]; penTypes: PenTypeInfo[]; layouts?: TestLayouts; kind: Kind;
  calibration?: Calibration; disabled?: boolean; canEdit: boolean; canGenerate: boolean; hint?: string;
  onSettings: (next: Settings) => void; onPen: (pen: Pen) => void; onPick: (test: TestKind) => void;
  onGenerate: (test: TestKind) => void; onApply: Apply;
}) {
  const pen = settings.pens[settings.active_pen];
  const mount = mountOf(pen);
  const type = penTypes.find(item => item.key === pen.pen_type);
  const [open, setOpen] = useState<TestKind | null>(isTest(kind) ? kind : null);
  return <div className="plotter-tests">
    <h3>Testes de espessura</h3>
    <div className="plotter-segments" role="group" aria-label="Suporte nos testes">
      {mounts.map(item => <button key={item.key} type="button" aria-pressed={mount === item.key} disabled={disabled}
        onClick={() => onSettings(selectMount(settings, item, penTypes))}>{item.name}</button>)}
    </div>
    <div className="plotter-fields"><PenTypeSelect pen={pen} types={penTypes} disabled={disabled || !canEdit} onChange={onPen} /></div>
    {type && <p className="plotter-muted">{type.about} Valores iniciais: aperto de {mm(pen.depth_min)} a {mm(pen.depth_max)} mm,
      traço de ~{mm(pen.line_width)} mm. São estimativas; os testes medem a sua caneta.</p>}
    <ol className="plotter-test-list">
      {TEST_KINDS.map(test => <li key={test}>
        <button type="button" className="plotter-test" aria-expanded={open === test} disabled={disabled}
          onClick={() => { const next = open === test ? null : test; setOpen(next); if (next) onPick(next); }}>
          <strong>{TEST_INFO[test].title}</strong><small>{TEST_INFO[test].summary}</small>
        </button>
        {open === test && <div className="plotter-test-body">
          <ol className="plotter-steps">{TEST_INFO[test].steps.map(step => <li key={step}>{step}</li>)}</ol>
          <button type="button" disabled={disabled || !canGenerate} onClick={() => onGenerate(test)}>Gerar e validar o teste</button>
          {hint && <p className="plotter-muted">{hint}</p>}
          <h4>Resultado medido</h4>
          <ResultForm test={test} pen={pen} layouts={layouts} calibration={calibration} disabled={disabled || !canEdit} onApply={onApply} />
        </div>}
      </li>)}
    </ol>
  </div>;
}
