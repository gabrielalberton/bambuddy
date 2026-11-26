import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, ImageUp, PenTool, Play, ScanEye } from 'lucide-react';
import { api, ApiError } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { drawableArea, plotter, type Config, type Drawing, type HistoryItem, type Kind, type Paper, type Pen, type Placement, type Plan, type Rect, type Settings } from './api';
import { Numeric, PenFields } from './Controls';
import { ContactAdjust } from './Contact';
import { DrawingHistory } from './History';
import { MountPicker } from './Mount';
import { ZSweepTest } from './Thickness';
import { calibrationText, sweepOptions, type SweepVariant } from './thickness';
import { FALLBACK_MOUNTS, MOUNT_ABOUT, mountOf } from './mounts';
import { Plate, type Edit, type Layer } from './Plate';
import { PlateCamera } from './PlateCamera';
import { PlateClear } from './PlateClear';
import { PLATE_TABS, type PlateTab } from './platePhoto';
import { loadSession, saveSession } from './session';
import { useAerialPlate } from './useAerialPlate';
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
  drawing: 'Desenho', zsweep: 'Teste de altura (contato ±2 mm)',
  cross: 'Cruz de alinhamento', frame: 'Contorno da área útil',
};
const HISTORY_KEY = ['custom', 'plotter', 'drawings'];

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
  const canClearPlate = !authEnabled || hasPermission('printers:clear_plate');
  const statusQuery = useQuery({
    queryKey: ['custom', 'plotter', id, 'status'], queryFn: () => plotter.status(id),
    refetchInterval: query => query.state.data?.jog ? 700 : 3000, retry: false,
  });
  const [restored] = useState(() => loadSession(id));
  const [settings, setSettings] = useState<Settings>(() => restored ? {
    ...initial, paper: restored.paper, active_pen: restored.activePen in initial.pens ? restored.activePen : initial.active_pen,
  } : initial);
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [excluded, setExcluded] = useState(new Set<number>(restored?.excluded));
  const [placement, setPlacement] = useState<Placement>(restored?.placement ?? initial.placement ?? { cx: 128, cy: 110, width: 150, rotation: 0 });
  const [layer, setLayer] = useState<Layer>('vector');
  const [edit, setEdit] = useState<Edit>('lock');
  const [kind, setKind] = useState<Kind>(restored?.kind ?? 'drawing');
  const [variant, setVariant] = useState<SweepVariant>(restored?.variant ?? 'reference');
  const [pressure, setPressure] = useState(restored?.pressure ?? 'variable');
  const [widthMode, setWidthMode] = useState(restored?.widthMode ?? 'fit');
  const [threshold, setThreshold] = useState<number | null>(restored?.threshold ?? null);
  const [background, setBackground] = useState(restored?.background ?? true);
  const [ink, setInk] = useState(restored?.ink ?? 'luma');
  const [invert, setInvert] = useState(restored?.invert ?? 'auto');
  const [plan, setPlan] = useState<Plan | null>(restored?.plan ?? null);
  const [time, setTime] = useState(0);
  const [travel, setTravel] = useState(true);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState('');
  const moves = useRef<Promise<void>>(Promise.resolve());
  const [calibOpen, setCalibOpen] = useState<boolean | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [imageUrl, setImageUrl] = useState<string>();
  const hasVision = config.printers.some(printer => printer.id === id && printer.plate_vision);
  const [aerialOn, setAerialOn] = useState(false);
  const [tab, setTab] = useState<PlateTab>(() => {
    try {
      const saved = localStorage.getItem('plotter-plate-tab');
      return PLATE_TABS.some(([value]) => value === saved) ? saved as PlateTab : 'none';
    } catch { return 'none'; }
  });
  const chooseTab = (value: PlateTab) => {
    setTab(value);
    try { localStorage.setItem('plotter-plate-tab', value); } catch { /* preference only */ }
  };
  const { aerial, status: aerialStatus } = useAerialPlate(id, aerialOn);
  const history = useQuery({ queryKey: HISTORY_KEY, queryFn: plotter.drawings, retry: false });
  const running = useRef(false);
  const positionCustomized = useRef(initial.placement !== null || !!restored?.customized);
  const pen = settings.pens[settings.active_pen];
  const mounts = config.mounts?.length ? config.mounts : FALLBACK_MOUNTS;
  const penTypes = config.pen_types ?? [];
  const mount = mountOf(pen);
  const mountInfo = mounts.find(item => item.key === mount);
  const samePens = Object.entries(settings.pens).filter(([, item]) => mountOf(item) === mount);
  const paper = settings.paper;
  const area = drawableArea(settings.machine, pen, paper);
  const status = statusQuery.error ? undefined : statusQuery.data;
  const jog = status?.jog;
  const end = plan?.sim.at(-1)?.[3] ?? 0;
  const options = { threshold, background, ink, invert };
  const calibrated = pen.z_contact !== null;
  const blocker = status?.blockers[0]?.text;
  const canStart = !!status && !blocker && !jog;
  const penChanged = JSON.stringify(pen) !== JSON.stringify(savedSettings.current.pens[settings.active_pen]);

  // Reabre o desenho do rascunho (a imagem fica no histórico do servidor).
  useEffect(() => {
    const wanted = restored?.drawingId;
    if (!wanted) return;
    let active = true;
    plotter.openDrawing(wanted).then(next => { if (active) setDrawing(current => current ?? next); }).catch(() => undefined);
    return () => { active = false; };
  }, [restored]);

  useEffect(() => {
    saveSession(id, {
      at: Date.now(), paper: settings.paper, placement, customized: positionCustomized.current, activePen: settings.active_pen,
      kind, variant, pressure, widthMode, threshold, background, ink, invert, excluded: [...excluded], drawingId: drawing?.id ?? restored?.drawingId ?? null, plan,
    });
  }, [id, settings.paper, settings.active_pen, placement, kind, variant, pressure, widthMode, threshold, background, ink, invert, excluded, drawing, plan, restored]);

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

  function showError(err: unknown) {
    const reasons = err instanceof ApiError ? err.detail?.reasons as { text: string }[] | undefined : undefined;
    setError(reasons?.length ? reasons.map(reason => reason.text).join(' ') : String((err as Error).message || err));
  }

  // Os ajustes de altura saem em fila (um depois do outro), sem travar a tela entre um toque e outro.
  function moveHeight(z: number) {
    const sent = moves.current.then(() => plotter.jogMove(id, z)).then(() => undefined);
    moves.current = sent.catch(() => undefined);
    setError('');
    return sent.catch(err => { showError(err); throw err; });
  }

  function run(label: string, task: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(label);
    setError('');
    setMessage('');
    void task().catch(showError).finally(() => {
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

  function show(next: Drawing) {
    invalidate();
    if (!positionCustomized.current) setPlacement(fit(next, area));
    setDrawing(next);
    setExcluded(new Set());
    setLayer('vector');
    setEdit('lock');
    setKind('drawing');
    void cache.invalidateQueries({ queryKey: HISTORY_KEY });
  }

  function upload(file: File) {
    if (file.size > config.max_upload_mb * 1024 * 1024) {
      setError(`O limite por imagem é de ${config.max_upload_mb} MB.`);
      return;
    }
    run('Vetorizando imagem…', async () => show(await plotter.drawing(file, options)));
  }

  /** Reabre uma imagem do histórico com as opções de vetorização usadas nela. */
  function reopen(item: HistoryItem) {
    run('Abrindo imagem…', async () => {
      const next = await plotter.openDrawing(item.id);
      const used = item.options;
      setThreshold(typeof used.threshold === 'number' ? used.threshold : null);
      setBackground(used.background !== false);
      setInk(used.ink === 'min' ? 'min' : 'luma');
      setInvert(used.invert === 'yes' || used.invert === 'no' ? used.invert : 'auto');
      show(next);
      setMessage(`“${item.name}” aberta do histórico.`);
    });
  }

  function forget(item: HistoryItem) {
    if (!window.confirm(`Excluir “${item.name}” do histórico?`)) return;
    run('Excluindo imagem…', async () => {
      await plotter.deleteDrawing(item.id);
      if (drawing?.id === item.id) {
        invalidate();
        setDrawing(null);
        setEdit('lock');
        setLayer('vector');
      }
      await cache.invalidateQueries({ queryKey: HISTORY_KEY });
      setMessage(`“${item.name}” excluída do histórico.`);
    });
  }

  async function makePlan(which: Kind) {
    setReady(false);
    const next = await plotter.plan(id, {
      kind: which, drawing_id: drawing?.id, placement, paper, pen_id: settings.active_pen,
      options: { pressure, width_mode: widthMode, exclude: [...excluded] },
      ...(which === 'zsweep' ? sweepOptions(variant) : {}),
      title: which === 'drawing' ? drawing?.meta.name : KIND_LABELS[which],
    });
    setPlan(next);
    setTime(next.sim.at(-1)?.[3] ?? 0);
    setLayer('simulation');
    return next;
  }

  function preview() {
    run('Gerando plano…', async () => {
      const next = await makePlan(kind);
      if (kind === 'zsweep') setMessage(next.ok ? 'Teste validado. Confira a simulação na mesa e inicie em “4 · Enviar”.' : 'Teste recusado: veja os motivos em “4 · Enviar”.');
    });
  }

  const imported = drawing ? `${drawing.meta.name} · ${drawing.strokes.length.toLocaleString('pt-BR')} traços` : 'PNG ou JPEG';
  const plotMessage = status?.plotting ? `Plotando · ${status.progress ?? 0}%` : blocker ?? (status?.connected ? 'A1 conectada' : 'Status da A1 indisponível');
  function section(title: string, body: ReactNode) {
    return <section className="plotter-card"><h2>{title}</h2>{body}</section>;
  }

  const paperSummary = `${config.paper_presets.find(preset => preset.w === paper.w && preset.h === paper.h)?.id ?? 'Personalizado'} · ${paper.w} × ${paper.h} mm · X ${paper.x} Y ${paper.y}`;
  const layers = [
    ...(drawing ? [['vector', 'Vetor'], ['original', 'Original'], ['overlay', 'Sobreposição']] as const : []),
    ...(plan ? [['simulation', 'Simulação']] as const : []),
  ];
  const canGenerate = canFiles && !!area && calibrated && !penChanged && !jog
    && (kind !== 'drawing' || (!!drawing && excluded.size < drawing.strokes.length));
  const generateHint = !calibrated ? 'Antes, calibre a altura de contato em “3 · Caneta”.'
    : penChanged ? 'Salve o perfil da caneta para aplicar as mudanças ao plano.'
    : !area ? 'O papel está fora do alcance da caneta.'
    : kind === 'drawing' && !drawing ? 'Selecione uma imagem.' : undefined;

  return <>
    <div className="plotter-messages" aria-live="polite">
      {error && <p role="alert" className="plotter-error">{error}</p>}
      {(busy || message) && <p>{busy || message}</p>}
    </div>
    <fieldset disabled={!!busy} className="plotter-workspace">
      <section className="plotter-card plotter-board">
        <div className="plotter-board-heading"><h2>Mesa da A1</h2><span>{settings.machine.plate_w} × {settings.machine.plate_h} mm</span></div>
        <div className="plotter-segments" role="group" aria-label="Mover na mesa">
          <button type="button" aria-pressed={edit === 'lock'} onClick={() => setEdit('lock')}>Travado</button>
          <button type="button" aria-pressed={edit === 'paper'} onClick={() => { setEdit('paper'); if (layer === 'simulation') setLayer('vector'); }}>Mover papel</button>
          {drawing && <button type="button" aria-pressed={edit === 'drawing'} onClick={() => { setEdit('drawing'); if (layer === 'simulation') setLayer('vector'); }}>Mover desenho</button>}
          {drawing && <button type="button" aria-pressed={edit === 'exclude'} onClick={() => { setEdit('exclude'); setLayer('vector'); }}>Editar traços</button>}
        </div>
        {edit === 'drawing' && drawing && <p className="plotter-muted">
          Arraste para mover. Use a pinça ou a roda do mouse sobre o desenho para dimensionar.
        </p>}
        {edit === 'exclude' && <p className="plotter-muted">Toque em um traço para excluir ou restaurar. Os excluídos aparecem em vermelho.</p>}
        <Plate machine={settings.machine} paper={paper} area={area} pen={pen} drawing={drawing} placement={placement}
          imageUrl={imageUrl} aerial={aerial} tab={tab} layer={layer} edit={edit} points={plan?.sim} time={time} travel={travel}
          locked={!!busy || !!jog || edit === 'lock'} onPaper={changePaper} onPlacement={changePlacement}
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
        {layers.length > 1 && <div className="plotter-segments" role="group" aria-label="Camada da prévia">
          {layers.map(([value, label]) =>
            <button key={value} type="button" aria-pressed={layer === value}
              onClick={() => { if (value === 'original' && edit === 'exclude') setEdit('drawing'); setLayer(value); }}>{label}</button>)}
        </div>}
        {layer === 'simulation' && <div className="plotter-simulation">
          <label><span>Posição no tempo · {showTime(time)} / {showTime(end)}</span>
            <input type="range" min={0} max={end} step={0.01} value={time} onChange={e => setTime(Number(e.target.value))} />
          </label>
          <label className="plotter-check"><input type="checkbox" checked={travel} onChange={e => setTravel(e.target.checked)} /> Mostrar deslocamentos no ar</label>
          <span className="plotter-gradient" /> <span>Menor a maior compressão</span>
        </div>}
        <details className="plotter-view">
          <summary>Visualização do prato</summary>
          <div className="plotter-segments" role="group" aria-label="Aba do prato (só aparência)">
            {PLATE_TABS.map(([value, label]) =>
              <button key={value} type="button" aria-pressed={tab === value} onClick={() => chooseTab(value)}>{label}</button>)}
          </div>
          {hasVision && <div className="plotter-aerial">
            <button type="button" aria-pressed={aerialOn} onClick={() => setAerialOn(on => !on)}>
              <ScanEye size={16} aria-hidden="true" /> {aerialOn ? 'Voltar à foto de referência' : 'Ver o prato real (vista aérea)'}
            </button>
            {aerialOn && <p className="plotter-muted" role="status">{aerialStatus}</p>}
          </div>}
          {hasVision && <PlateCamera id={id} />}
        </details>
      </section>
      <div className="plotter-sidebar">
        {section('1 · O que plotar', <>
          <label className="plotter-field"><span>Trabalho</span>
            <select aria-label="Trabalho" value={kind} onChange={e => { setKind(e.target.value as Kind); invalidate(); }}>
              {Object.entries(KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {kind === 'drawing' && <>
            <label className="plotter-upload"><ImageUp size={22} aria-hidden="true" />
              <span><strong>Selecionar imagem</strong><small>{imported}</small></span>
              <input type="file" aria-label="Selecionar imagem" accept="image/png,image/jpeg,.png,.jpg,.jpeg" disabled={!canFiles}
                onChange={e => { const file = e.currentTarget.files?.[0]; if (file) upload(file); e.currentTarget.value = ''; }} />
            </label>
            {history.error && <p className="plotter-muted">Histórico indisponível. {history.error.message}</p>}
            <DrawingHistory items={history.data?.items ?? []} keep={history.data?.keep} current={drawing?.id}
              disabled={!!busy} canDelete={canFiles} onOpen={reopen} onDelete={forget} />
            {drawing && <details><summary>Posição e tamanho do desenho</summary>
              <div className="plotter-fields">{POSITION_FIELDS.map(([key, label, min, max]) => <Numeric key={key} label={label} value={placement[key]} min={min} max={max}
                onChange={value => { if (value !== null && value !== placement[key]) changePlacement({ ...placement, [key]: value }); }} />)}</div>
              <div className="plotter-actions">
                <button type="button" disabled={!area} onClick={() => changePlacement(fit(drawing, area))}>Ajustar à área útil</button>
                {excluded.size > 0 && <button type="button" onClick={() => { setExcluded(new Set()); invalidate(); }}>
                  Restaurar {excluded.size} {excluded.size === 1 ? 'traço' : 'traços'}
                </button>}
              </div>
            </details>}
            <details><summary>Opções de vetorização e de pressão</summary>
              <div className="plotter-fields">
                <Numeric label="Limiar (0–1, vazio = auto)" value={threshold} min={0.03} max={0.97} nullable onChange={setThreshold} />
                <label className="plotter-field"><span>Tipo de tinta</span>
                  <select aria-label="Tipo de tinta" value={ink} onChange={e => setInk(e.target.value)}><option value="luma">Escura</option><option value="min">Colorida</option></select>
                </label>
                <label className="plotter-field"><span>Polaridade</span>
                  <select aria-label="Polaridade" value={invert} onChange={e => setInvert(e.target.value)}><option value="auto">Automática</option><option value="no">Traço escuro</option><option value="yes">Traço claro</option></select>
                </label>
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
              </div>
              <label className="plotter-check"><input type="checkbox" checked={background} onChange={e => setBackground(e.target.checked)} /> Compensar iluminação do papel</label>
              <button type="button" disabled={!drawing || !canFiles} onClick={() => drawing && run('Vetorizando novamente…', async () => {
                const next = await plotter.revectorize(drawing, options);
                invalidate(); setDrawing(next); setExcluded(new Set());
              })}>Vetorizar novamente</button>
            </details>
          </>}
          {kind === 'zsweep' && <ZSweepTest contact={pen.z_contact} variant={variant} onVariant={next => { setVariant(next); invalidate(); }} />}
          {kind === 'cross' && <p className="plotter-muted">Cruz leve no meio da área útil para conferir o alinhamento da caneta.</p>}
          {kind === 'frame' && <p className="plotter-muted">Contorno da área útil para conferir onde o papel está.</p>}
        </>)}
        <section className="plotter-card plotter-fold">
          <details open={!area}>
            <summary><h2>2 · Papel</h2><span className="plotter-muted">{paperSummary}</span></summary>
            <fieldset disabled={!!jog}>
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
            </fieldset>
          </details>
        </section>
        <section className="plotter-card plotter-fold">
          <details open={!!jog || (calibOpen ?? !calibrated)} onToggle={e => setCalibOpen(e.currentTarget.open)}>
            <summary><h2>3 · Caneta</h2>
              <span className="plotter-muted">{penTypes.find(item => item.key === pen.pen_type)?.name ?? pen.name} · {mountInfo?.name ?? mount} · {calibrated ? `contato Z ${pen.z_contact} mm` : 'contato pendente'}</span></summary>
            <MountPicker settings={settings} mounts={mounts} penTypes={penTypes} disabled={!!jog || !!busy}
              onChange={next => { invalidate(); setSettings(next); }} />
            <ContactAdjust jog={jog} contact={pen.z_contact} steps={(mountInfo?.jog_steps ?? [0.1, 0.5]).filter(step => Math.abs(step) <= config.limits.jog_max_step)}
              hint={MOUNT_ABOUT[mount].contact} canControl={canControl} canStart={!!area && canStart}
              reason={!canControl ? 'Seu usuário não tem permissão para mover a impressora.' : !area ? 'O papel não tem área útil dentro do alcance da caneta.' : jog ? undefined : blocker}
              onStart={() => run('Fazendo homing…', async () => {
                invalidate();
                const saved = await saveSettings();
                await plotter.jogStart(id, saved.active_pen);
                await statusQuery.refetch();
              })}
              onMove={moveHeight}
              onFinish={save => run('Recolhendo caneta…', async () => {
                await moves.current;
                await plotter.jogFinish(id, save);
                await statusQuery.refetch();
                const saved = await plotter.settings(id);
                applySaved(saved);
                invalidate();
                setMessage(save ? 'Altura de contato salva.' : 'Ajuste encerrado.');
              })} />
            <details><summary>Perfil da caneta</summary>
              <fieldset disabled={!!jog || !canControl}>
                {samePens.length > 1 && <label className="plotter-field"><span>Perfil ativo</span>
                  <select aria-label="Perfil ativo" value={settings.active_pen} onChange={e => { invalidate(); setSettings({ ...settings, active_pen: e.target.value }); }}>
                    {samePens.map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}
                  </select>
                </label>}
                <PenFields pen={pen} mount={mountInfo} penTypes={penTypes} onChange={changePen} />
                <div className="plotter-actions">
                  <button type="button" onClick={() => run('Salvando ajustes…', async () => { await saveSettings(); invalidate(); setMessage('Ajustes salvos.'); })}>Salvar ajustes</button>
                </div>
              </fieldset>
            </details>
          </details>
        </section>
        {section('4 · Enviar', <>
          <p className="plotter-muted" role="status">{plotMessage}</p>
          <button type="button" disabled={!canGenerate} onClick={preview}>Gerar e validar plano</button>
          {generateHint && <p className="plotter-muted">{generateHint}</p>}
          {plan && <div className="plotter-result" aria-live="polite">
            <strong>{plan.ok ? 'G-code validado' : 'Plano recusado'}{plan.stats.time_s !== undefined ? ` · ${showTime(plan.stats.time_s)} estimados` : ''}</strong>
            {!!calibrationText(plan.calibration) && <p>{calibrationText(plan.calibration)}</p>}
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
          <PlateClear needed={!!status?.blockers.some(item => item.code === 'plate_not_cleared')} allowed={canClearPlate}
            onConfirm={() => run('Confirmando mesa liberada…', async () => {
              await api.clearPlate(id);
              await statusQuery.refetch();
              setMessage('Mesa liberada.');
            })} />
          {canControl && <label className="plotter-check">
            <input type="checkbox" checked={ready} disabled={!!jog} onChange={e => setReady(e.target.checked)} />
            Estou junto à A1. O suporte está montado {mount === 'rigid' ? 'sem mola (caneta travada)' : 'com mola'} e a caneta,
            no lugar; o papel está fixo na posição indicada e o trajeto está livre.
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
