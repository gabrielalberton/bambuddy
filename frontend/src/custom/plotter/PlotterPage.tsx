import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, ImageUp, PenTool, Play } from 'lucide-react';
import { ApiError } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { drawableArea, plotter, type Config, type Drawing, type Kind, type Paper, type Pen, type Placement, type Plan, type Rect, type Settings } from './api';
import { Numeric, PenFields } from './Controls';
import { Plate, type Edit, type Layer } from './Plate';
import { usePlotterConfig } from './navigation';
import './plotter.css';

const PAPER_FIELDS: [keyof Paper, string, number, number][] = [
  ['w', 'Largura (mm)', 10, 600], ['h', 'Altura (mm)', 10, 600],
  ['x', 'Papel X (mm)', -400, 400], ['y', 'Papel Y (mm)', -400, 400],
  ['margin', 'Margem (mm)', 0, 50], ['thickness', 'Espessura (mm)', 0, 2],
];
const POSITION_FIELDS: [keyof Placement, string, number, number][] = [
  ['width', 'Largura (mm)', 1, 1000], ['rotation', 'Rotação (°)', -360, 360],
  ['cx', 'Centro X (mm)', -500, 800], ['cy', 'Centro Y (mm)', -500, 800],
];
const KIND_LABELS: Record<Kind, string> = {
  drawing: 'Desenho', ladder: 'Escala de pressão', cross: 'Cruz de alinhamento', frame: 'Contorno da área útil',
};

function fit(drawing: Drawing, area: Rect | null): Placement {
  const [x0, y0, x1, y1] = area ?? [0, 0, 256, 256];
  const width = Math.min(x1 - x0, (y1 - y0) * drawing.width / drawing.height) * 0.9;
  return { width: Math.max(1, Math.round(width * 10) / 10), cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, rotation: 0 };
}

function showTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

export function PlotterPage() {
  const config = usePlotterConfig();
  const [printerId, setPrinterId] = useState<number | null>(null);
  const printers = config.data?.printers.filter(item => item.supported) ?? [];
  const printer = printers.find(item => item.id === printerId) ?? printers[0];
  return <div className="plotter">
    <header className="plotter-header">
      <div><h1><PenTool size={26} aria-hidden="true" /> Plotter</h1><p>Bambu Lab A1 · Plotagem com caneta</p></div>
      {printers.length > 1 && <label className="plotter-field"><span>Impressora</span>
        <select aria-label="Impressora" value={printer.id} onChange={e => setPrinterId(Number(e.target.value))}>
          {printers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>}
    </header>
    {config.isPending ? <p>Carregando plotter…</p> : config.error ? <p role="alert">Plotter indisponível. {config.error.message}
      <button className="plotter-retry" onClick={() => void config.refetch()}>Tentar novamente</button></p>
      : printer ? <PrinterPlotter key={printer.id} id={printer.id} config={config.data!} />
        : <p>Adicione uma Bambu Lab A1 no Bambuddy para usar o plotter.</p>}
  </div>;
}

function PrinterPlotter({ id, config }: { id: number; config: Config }) {
  const settings = useQuery({ queryKey: ['custom', 'plotter', id, 'settings'], queryFn: () => plotter.settings(id), retry: false });
  if (settings.error) return <p role="alert">{settings.error.message} <button onClick={() => void settings.refetch()}>Tentar novamente</button></p>;
  return settings.data ? <Workspace id={id} config={config} initial={settings.data} /> : <p>Carregando ajustes…</p>;
}

function Workspace({ id, config, initial }: { id: number; config: Config; initial: Settings }) {
  const { authEnabled, hasPermission } = useAuth();
  const cache = useQueryClient();
  const savedSettings = useRef(initial);
  const canFiles = !authEnabled || hasPermission('printers:files');
  const canControl = !authEnabled || hasPermission('printers:control');
  const statusQuery = useQuery({
    queryKey: ['custom', 'plotter', id, 'status'], queryFn: () => plotter.status(id),
    refetchInterval: query => query.state.data?.jog ? 700 : 3000, retry: false,
  });
  const [settings, setSettings] = useState(initial);
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [excluded, setExcluded] = useState(new Set<number>());
  const [placement, setPlacement] = useState<Placement>(initial.placement ?? { cx: 128, cy: 110, width: 150, rotation: 0 });
  const [layer, setLayer] = useState<Layer>('vector');
  const [edit, setEdit] = useState<Edit>('paper');
  const [kind, setKind] = useState<Kind>('drawing');
  const [pressure, setPressure] = useState('variable');
  const [widthMode, setWidthMode] = useState('fit');
  const [threshold, setThreshold] = useState<number | null>(null);
  const [background, setBackground] = useState(true);
  const [ink, setInk] = useState('luma');
  const [invert, setInvert] = useState('auto');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [time, setTime] = useState(0);
  const [travel, setTravel] = useState(true);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [imageUrl, setImageUrl] = useState<string>();
  const running = useRef(false);
  const positionCustomized = useRef(initial.placement !== null);
  const pen = settings.pens[settings.active_pen];
  const paper = settings.paper;
  const area = drawableArea(settings.machine, pen, paper);
  const status = statusQuery.error ? undefined : statusQuery.data;
  const jog = status?.jog;
  const end = plan?.sim.at(-1)?.[3] ?? 0;
  const options = { threshold, background, ink, invert };
  const hasPressure = pen.table.length > 1 && Math.max(...pen.table.map(row => row[1])) > Math.min(...pen.table.map(row => row[1]));
  const blocker = status?.blockers[0]?.text;
  const canStart = !!status && !blocker && !jog;
  const penChanged = JSON.stringify(pen) !== JSON.stringify(savedSettings.current.pens[settings.active_pen]);

  useEffect(() => {
    if (!drawing || (layer !== 'original' && layer !== 'overlay')) return;
    let active = true;
    let url: string | undefined;
    plotter.image(drawing).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob);
      setImageUrl(url);
    }).catch(err => { if (active) setError(err.message); });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
      setImageUrl(undefined);
    };
  }, [drawing, layer]);

  function invalidate() {
    setReady(false);
    setPlan(null);
    setLayer(current => current === 'simulation' ? 'vector' : current);
  }

  function run(label: string, task: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(label);
    setError('');
    setMessage('');
    void task().catch(err => {
      const reasons = err instanceof ApiError ? err.detail?.reasons as { text: string }[] | undefined : undefined;
      setError(reasons?.length ? reasons.map(reason => reason.text).join(' ') : String(err.message || err));
    }).finally(() => {
      running.current = false;
      setBusy('');
    });
  }

  function changePaper(next: Paper) {
    invalidate();
    setSettings({ ...settings, paper: next });
  }

  function changePlacement(next: Placement) {
    invalidate();
    positionCustomized.current = true;
    setPlacement(next);
  }

  function changePen(value: Pen) {
    invalidate();
    setSettings({ ...settings, pens: { ...settings.pens, [settings.active_pen]: value } });
  }

  async function saveSettings() {
    const saved = await plotter.save(id, { ...settings, placement: drawing ? placement : settings.placement });
    applySaved(saved);
    return saved;
  }

  function applySaved(saved: Settings) {
    savedSettings.current = saved;
    cache.setQueryData(['custom', 'plotter', id, 'settings'], saved);
    setSettings(saved);
  }

  function upload(file: File) {
    if (file.size > config.max_upload_mb * 1024 * 1024) {
      setError(`O limite por imagem é de ${config.max_upload_mb} MB.`);
      return;
    }
    run('Vetorizando imagem…', async () => {
      const next = await plotter.drawing(file, options);
      invalidate();
      if (!positionCustomized.current) setPlacement(fit(next, area));
      setDrawing(next);
      setExcluded(new Set());
      setLayer('vector');
      setEdit('drawing');
      setKind('drawing');
    });
  }

  function preview() {
    run('Gerando plano…', async () => {
      setReady(false);
      const next = await plotter.plan(id, {
        kind, drawing_id: drawing?.id, placement, paper, pen_id: settings.active_pen,
        options: { pressure, width_mode: widthMode, exclude: [...excluded] }, title: kind === 'drawing' ? drawing?.meta.name : KIND_LABELS[kind],
      });
      setPlan(next);
      setTime(next.sim.at(-1)?.[3] ?? 0);
      setLayer('simulation');
    });
  }

  const imported = drawing ? `${drawing.meta.name} · ${drawing.strokes.length.toLocaleString('pt-BR')} traços` : 'PNG ou JPEG';
  const plotMessage = status?.plotting ? `Plotando · ${status.progress ?? 0}%` : blocker ?? (status?.connected ? 'A1 conectada' : 'Status da A1 indisponível');
  function section(title: string, body: ReactNode) {
    return <section className="plotter-card"><h2>{title}</h2>{body}</section>;
  }

  return <>
    <div className="plotter-messages" aria-live="polite">
      {error && <p role="alert" className="plotter-error">{error}</p>}
      {(busy || message) && <p>{busy || message}</p>}
    </div>
    <fieldset disabled={!!busy} className="plotter-workspace">
      <section className="plotter-card plotter-board">
        <div className="plotter-board-heading"><h2>Mesa da A1</h2><span>{settings.machine.plate_w} × {settings.machine.plate_h} mm</span></div>
        <div className="plotter-segments" aria-label="Mover na mesa">
          <button type="button" aria-pressed={edit === 'paper' && layer !== 'simulation'} onClick={() => { setEdit('paper'); if (layer === 'simulation') setLayer('vector'); }}>Mover papel</button>
          <button type="button" aria-pressed={edit === 'drawing' && layer !== 'simulation'} disabled={!drawing} onClick={() => { setEdit('drawing'); if (layer === 'simulation') setLayer('vector'); }}>Mover desenho</button>
          <button type="button" aria-pressed={edit === 'exclude' && layer !== 'simulation'} disabled={!drawing}
            onClick={() => { setEdit('exclude'); setLayer('vector'); }}>Editar traços</button>
        </div>
        {edit === 'exclude' && layer !== 'simulation' && <p className="plotter-muted">Toque em um traço para excluir ou restaurar. Os excluídos aparecem em vermelho.</p>}
        <Plate machine={settings.machine} paper={paper} area={area} pen={pen} drawing={drawing} placement={placement}
          imageUrl={imageUrl} layer={layer} edit={edit} points={plan?.sim} time={time} travel={travel}
          locked={!!busy || !!jog || layer === 'simulation'} onPaper={changePaper} onPlacement={changePlacement}
          excluded={excluded} onToggleStroke={index => {
            const next = new Set(excluded);
            if (next.has(index)) next.delete(index);
            else next.add(index);
            setExcluded(next);
            invalidate();
          }} />
        <div className="plotter-key"><span><i className="plotter-swatch paper" /> Papel</span><span><i className="plotter-swatch bed" /> Mesa</span>
          {area ? <span><i className="plotter-swatch area" /> Área útil</span> : <span className="plotter-error">Papel fora do alcance</span>}
        </div>
        <div className="plotter-segments" aria-label="Camada da prévia">
          {([['vector', 'Vetor'], ['original', 'Original'], ['overlay', 'Sobreposição'], ['simulation', 'Simulação']] as const).map(([value, label]) =>
            <button key={value} type="button" aria-pressed={layer === value} disabled={value === 'simulation' ? !plan : !drawing}
              onClick={() => { if (value === 'original' && edit === 'exclude') setEdit('drawing'); setLayer(value); }}>{label}</button>)}
        </div>
        {layer === 'simulation' && <div className="plotter-simulation">
          <label><span>Posição no tempo · {showTime(time)} / {showTime(end)}</span>
            <input type="range" min={0} max={end} step={0.01} value={time} onChange={e => setTime(Number(e.target.value))} />
          </label>
          <label className="plotter-check"><input type="checkbox" checked={travel} onChange={e => setTravel(e.target.checked)} /> Mostrar deslocamentos no ar</label>
          <span className="plotter-gradient" /> <span>Menor a maior compressão</span>
        </div>}
      </section>
      <div className="plotter-sidebar">
        {section('Imagem', <>
          <label className="plotter-upload"><ImageUp size={22} aria-hidden="true" />
            <span><strong>Selecionar imagem</strong><small>{imported}</small></span>
            <input type="file" aria-label="Selecionar imagem" accept="image/png,image/jpeg,.png,.jpg,.jpeg" disabled={!canFiles}
              onChange={e => { const file = e.currentTarget.files?.[0]; if (file) upload(file); e.currentTarget.value = ''; }} />
          </label>
          <details><summary>Opções de vetorização</summary>
            <div className="plotter-fields">
              <Numeric label="Limiar (0–1, vazio = auto)" value={threshold} min={0.03} max={0.97} nullable onChange={setThreshold} />
              <label className="plotter-field"><span>Tipo de tinta</span>
                <select aria-label="Tipo de tinta" value={ink} onChange={e => setInk(e.target.value)}><option value="luma">Escura</option><option value="min">Colorida</option></select>
              </label>
              <label className="plotter-field"><span>Polaridade</span>
                <select aria-label="Polaridade" value={invert} onChange={e => setInvert(e.target.value)}><option value="auto">Automática</option><option value="no">Traço escuro</option><option value="yes">Traço claro</option></select>
              </label>
            </div>
            <label className="plotter-check"><input type="checkbox" checked={background} onChange={e => setBackground(e.target.checked)} /> Compensar iluminação do papel</label>
            <button type="button" disabled={!drawing || !canFiles} onClick={() => drawing && run('Vetorizando novamente…', async () => {
              const next = await plotter.revectorize(drawing, options);
              invalidate(); setDrawing(next); setExcluded(new Set());
            })}>Vetorizar novamente</button>
          </details>
        </>)}
        {section('Papel', <fieldset disabled={!!jog}>
          <div className="plotter-fields">
            <label className="plotter-field"><span>Formato</span>
              <select aria-label="Formato" value={config.paper_presets.find(preset => preset.w === paper.w && preset.h === paper.h)?.id ?? ''}
                onChange={e => {
                  const preset = config.paper_presets.find(item => item.id === e.target.value);
                  if (preset) changePaper({ ...paper, w: preset.w, h: preset.h });
                }}>
                <option value="">Personalizado</option>
                {config.paper_presets.map(preset => <option key={preset.id}>{preset.id}</option>)}
              </select>
            </label>
            <button className="plotter-swap" type="button" onClick={() => changePaper({ ...paper, w: paper.h, h: paper.w })}>Girar formato 90°</button>
            {PAPER_FIELDS.map(([key, label, min, max]) => <Numeric key={key} label={label} value={paper[key]} min={min} max={max}
              onChange={value => { if (value !== null && value !== paper[key]) changePaper({ ...paper, [key]: value }); }} />)}
          </div>
        </fieldset>)}
        {drawing && section('Posição do desenho', <>
          <div className="plotter-fields">{POSITION_FIELDS.map(([key, label, min, max]) => <Numeric key={key} label={label} value={placement[key]} min={min} max={max}
            onChange={value => { if (value !== null && value !== placement[key]) changePlacement({ ...placement, [key]: value }); }} />)}</div>
          <div className="plotter-actions">
            <button type="button" disabled={!area} onClick={() => changePlacement(fit(drawing, area))}>Ajustar à área útil</button>
            {excluded.size > 0 && <button type="button" onClick={() => { setExcluded(new Set()); invalidate(); }}>
              Restaurar {excluded.size} {excluded.size === 1 ? 'traço' : 'traços'}
            </button>}
          </div>
        </>)}
        {section('Calibração da caneta', <>
          <p className="plotter-muted">{pen.name} · {pen.z_contact === null ? 'Contato pendente' : `Contato Z ${pen.z_contact} mm`} · {hasPressure ? 'Curva de pressão medida' : 'Curva de pressão pendente'}</p>
          <details open={jog ? true : undefined}><summary>Editar perfil e ajustar contato</summary>
            <fieldset disabled={!!jog || !canControl}>
              {Object.keys(settings.pens).length > 1 && <label className="plotter-field"><span>Perfil ativo</span>
                <select aria-label="Perfil ativo" value={settings.active_pen} onChange={e => { invalidate(); setSettings({ ...settings, active_pen: e.target.value }); }}>
                  {Object.entries(settings.pens).map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}
                </select>
              </label>}
              <PenFields pen={pen} onChange={changePen} />
              <div className="plotter-actions">
                <button type="button" onClick={() => run('Salvando ajustes…', async () => { await saveSettings(); invalidate(); setMessage('Ajustes salvos.'); })}>Salvar ajustes</button>
                <button type="button" disabled={!area || !canStart || !ready} onClick={() => run('Iniciando ajuste de altura…', async () => {
                  invalidate();
                  const saved = await saveSettings();
                  await plotter.jogStart(id, saved.active_pen);
                  await statusQuery.refetch();
                })}>Iniciar ajuste de altura</button>
              </div>
              <p className="plotter-muted">Confirme a montagem em “Operação” antes de iniciar o ajuste de altura.</p>
            </fieldset>
            {jog && <>
              <p role="status">Z atual {jog.z.toFixed(2)} mm {jog.settling > 0 ? '· Aguarde o movimento' : ''}</p>
              <div className="plotter-actions">
                {[-0.5, -0.1, 0.1, 0.5].filter(step => Math.abs(step) <= config.limits.jog_max_step).map(step =>
                  <button key={step} type="button" disabled={!canControl || jog.settling > 0 || jog.z + step < jog.floor - 1e-9 || jog.z + step > jog.max + 1e-9}
                    onClick={() => run('Ajustando altura…', async () => { await plotter.jogMove(id, jog.z + step); await statusQuery.refetch(); })}>
                    {step > 0 ? '+' : ''}{step} mm
                  </button>)}
              </div>
              <div className="plotter-actions">
                {[true, false].map(save => <button key={String(save)} type="button" disabled={!canControl || jog.settling > 0}
                  onClick={() => run('Recolhendo caneta…', async () => {
                    await plotter.jogFinish(id, save);
                    await statusQuery.refetch();
                    const saved = await plotter.settings(id);
                    applySaved(saved);
                    invalidate();
                    setMessage(save ? 'Altura de contato salva.' : 'Ajuste encerrado.');
                  })}>{save ? 'Salvar contato e levantar' : 'Levantar sem salvar'}</button>)}
              </div>
            </>}
          </details>
        </>)}
        {section('Operação', <>
          <p className="plotter-muted" role="status">{plotMessage}</p>
          <div className="plotter-fields">
            <label className="plotter-field"><span>Trabalho</span>
              <select aria-label="Trabalho" value={kind} onChange={e => { setKind(e.target.value as Kind); invalidate(); }}>
                {Object.entries(KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            {kind === 'drawing' && <>
              <label className="plotter-field"><span>Pressão</span>
                <select aria-label="Pressão" value={pressure} onChange={e => { setPressure(e.target.value); invalidate(); }}>
                  <option value="variable">Variável</option><option value="constant">Constante</option>
                </select>
              </label>
              {pressure === 'variable' && <label className="plotter-field"><span>Largura do traço</span>
                <select aria-label="Largura do traço" value={widthMode} onChange={e => { setWidthMode(e.target.value); invalidate(); }}>
                  <option value="fit">Adaptar à faixa da caneta</option><option value="physical">Escala física da imagem</option>
                </select>
              </label>}
            </>}
          </div>
          {penChanged && <p className="plotter-muted">Salve o perfil da caneta para aplicar as mudanças ao plano.</p>}
          <button type="button" disabled={!canFiles || !area || penChanged || (kind === 'drawing' && (!drawing || excluded.size === drawing.strokes.length)) || !!jog} onClick={preview}>Gerar e validar plano</button>
          {plan && <div className="plotter-result" aria-live="polite">
            <strong>{plan.ok ? 'G-code validado' : 'Plano recusado'}{plan.stats.time_s !== undefined ? ` · ${showTime(plan.stats.time_s)} estimados` : ''}</strong>
            {!!plan.calibration.rows?.length && <p>Compressões, de cima para baixo: {plan.calibration.rows.map(row => row.depth).join(' · ')} mm</p>}
            {[...plan.errors, ...plan.warnings].map((notice, index) => <p key={index}>{notice.text}</p>)}
            {plan.ok && <button type="button" onClick={() => run('Baixando G-code…', async () => {
              const url = URL.createObjectURL(await plotter.download(id, plan));
              const link = document.createElement('a');
              link.href = url;
              link.download = `${plan.title.replace(/[^\p{L}\p{N}_-]+/gu, '_')}.gcode.3mf`;
              link.click();
              window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
            })}><Download size={17} aria-hidden="true" /> Baixar .gcode.3mf</button>}
          </div>}
          {canControl && <label className="plotter-check">
            <input type="checkbox" checked={ready} disabled={!!jog} onChange={e => setReady(e.target.checked)} />
            Estou junto à A1. O suporte e a caneta estão montados, o papel está fixo na posição indicada e o trajeto está livre.
          </label>}
          <button className="plotter-primary" type="button" disabled={!canControl || !plan?.ok || !ready || !canStart}
            onClick={() => plan && run('Enviando para a A1…', async () => {
              setReady(false);
              await plotter.start(id, plan);
              await statusQuery.refetch();
              setMessage('Comando aceito pela A1. Acompanhe o início na impressora.');
              setPlan(null);
              setLayer('vector');
            })}><Play size={17} aria-hidden="true" /> Iniciar plotagem</button>
        </>)}
      </div>
    </fieldset>
  </>;
}
