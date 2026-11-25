import { useState } from 'react';
import type { Pen } from './api';

type NumberProps = {
  label: string; value: number | null; onChange: (value: number | null) => void;
  min?: number; max?: number; nullable?: boolean;
};

export function Numeric({ label, value, onChange, min, max, nullable }: NumberProps) {
  const [draft, setDraft] = useState<string | null>(null);
  return <label className="plotter-field">
    <span>{label}</span>
    <input type="number" inputMode="decimal" step="any" min={min} max={max}
      value={draft ?? value ?? ''} onChange={e => setDraft(e.target.value)}
      onBlur={e => {
        const raw = e.target.value;
        if (raw === '' && nullable) onChange(null);
        const next = Number(raw);
        if (raw !== '' && Number.isFinite(next)) onChange(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next)));
        setDraft(null);
      }}
      onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}
    />
  </label>;
}

type NumericPenKey = Exclude<keyof Pen, 'name' | 'table' | 'use_mesh' | 'z_contact'>;
const penFields: [NumericPenKey, string, number, number][] = [
  ['offset_x', 'Deslocamento X (mm)', -80, 80],
  ['offset_y', 'Deslocamento Y (mm)', -80, 80],
  ['lift', 'Elevação entre traços (mm)', 0.5, 20],
  ['depth_min', 'Compressão mínima (mm)', 0, 6],
  ['depth_max', 'Compressão máxima (mm)', 0, 6],
  ['max_compression', 'Limite do suporte (mm)', 0.2, 8],
  ['line_width', 'Largura nominal do traço (mm)', 0.05, 10],
  ['draw_speed', 'Velocidade ao desenhar (mm/s)', 1, 150],
  ['travel_speed', 'Deslocamento no ar (mm/s)', 5, 300],
  ['z_speed', 'Velocidade Z (mm/s)', 1, 25],
  ['dwell_ms', 'Pausa para marcar pontos (ms)', 0, 2000],
];

export function PenFields({ pen, onChange }: { pen: Pen; onChange: (value: Pen) => void }) {
  return <>
    <div className="plotter-fields">
      <label className="plotter-field"><span>Nome da caneta</span>
        <input maxLength={60} value={pen.name} onChange={e => onChange({ ...pen, name: e.target.value })} />
      </label>
      <Numeric label="Altura de contato Z (mm)" value={pen.z_contact} min={0.3} max={40} nullable
        onChange={z_contact => onChange({ ...pen, z_contact })} />
      {penFields.map(([key, label, min, max]) => <Numeric key={key} label={label} value={pen[key]} min={min} max={max}
        onChange={value => { if (value !== null) onChange({ ...pen, [key]: value }); }} />)}
    </div>
    <label className="plotter-check"><input type="checkbox" checked={pen.use_mesh}
      onChange={e => onChange({ ...pen, use_mesh: e.target.checked })} /> Usar malha de nivelamento salva</label>
    <h4>Medidas de pressão</h4>
    <p className="plotter-muted">Meça a largura de cada linha do teste e informe o par compressão e largura em mm.</p>
    {pen.table.map(([depth, width], index) => <div className="plotter-measure" key={index}>
      <Numeric label="Compressão" value={depth} min={0} max={pen.max_compression} onChange={value => {
        if (value !== null) onChange({ ...pen, table: pen.table.map((row, i) => i === index ? [value, width] : row) });
      }} />
      <Numeric label="Largura" value={width} min={0.02} max={20} onChange={value => {
        if (value !== null) onChange({ ...pen, table: pen.table.map((row, i) => i === index ? [depth, value] : row) });
      }} />
      <button type="button" aria-label={`Remover medida ${index + 1}`}
        onClick={() => onChange({ ...pen, table: pen.table.filter((_, i) => i !== index) })}>×</button>
    </div>)}
    <button type="button" disabled={pen.table.length >= 24} onClick={() => onChange({
      ...pen, table: [...pen.table, [pen.table.length ? pen.depth_max : pen.depth_min, pen.line_width]],
    })}>Adicionar medida</button>
  </>;
}
