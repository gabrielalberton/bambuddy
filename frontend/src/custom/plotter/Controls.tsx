import { useState } from 'react';
import type { MountInfo, Pen, PenTypeInfo } from './api';
import { mountOf } from './mounts';
import { applyPenType } from './thickness';

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

type NumericPenKey = Exclude<keyof Pen, 'name' | 'table' | 'use_mesh' | 'z_contact' | 'mount' | 'pen_type'>;

/** Tipo de caneta: aplica os valores iniciais do tipo no modo atual e zera contato e medidas. */
export function PenTypeSelect({ pen, types, disabled, onChange }: {
  pen: Pen; types: PenTypeInfo[]; disabled?: boolean; onChange: (pen: Pen) => void;
}) {
  if (!types.length) return null;
  const current = types.find(type => type.key === pen.pen_type);
  return <label className="plotter-field"><span>Tipo de caneta</span>
    <select aria-label="Tipo de caneta" value={pen.pen_type} disabled={disabled} onChange={e => {
      const next = types.find(type => type.key === e.target.value);
      if (next && next.key !== pen.pen_type) onChange(applyPenType(pen, next, current, mountOf(pen)));
    }}>
      {!current && <option value={pen.pen_type}>{pen.pen_type}</option>}
      {types.map(type => <option key={type.key} value={type.key}>{type.name}</option>)}
    </select>
    <small className="plotter-muted">Trocar o tipo aplica os valores iniciais dele e zera o contato e as medidas.</small>
  </label>;
}

/** Campos numéricos do perfil; os limites de aperto vêm do modo do suporte (com mola aceita bem mais). */
function penFields(pen: Pen, mount?: MountInfo): [NumericPenKey, string, number, number][] {
  const rigid = pen.mount === 'rigid';
  const depthLimit = mount?.depth_limit ?? (rigid ? 2 : 6);
  const compressionLimit = mount?.compression_limit ?? (rigid ? 2 : 8);
  return [
    ['offset_x', 'Deslocamento X (mm)', -80, 80],
    ['offset_y', 'Deslocamento Y (mm)', -80, 80],
    ['lift', 'Elevação entre traços (mm)', 0.5, 20],
    ['depth_min', rigid ? 'Aperto mínimo da ponta (mm)' : 'Compressão mínima (mm)', 0, depthLimit],
    ['depth_max', rigid ? 'Aperto máximo do traço (mm)' : 'Compressão máxima (mm)', 0, depthLimit],
    ['max_compression', rigid ? 'Limite da ponta (mm)' : 'Curso útil da mola (mm)', 0.05, compressionLimit],
    ...PEN_FIELDS_REST,
  ];
}

const PEN_FIELDS_REST: [NumericPenKey, string, number, number][] = [
  ['line_width', 'Largura nominal do traço (mm)', 0.05, 10],
  ['draw_speed', 'Velocidade ao desenhar (mm/s)', 1, 150],
  ['travel_speed', 'Deslocamento no ar (mm/s)', 5, 300],
  ['z_speed', 'Velocidade Z (mm/s)', 1, 25],
  ['dwell_ms', 'Pausa para marcar pontos (ms)', 0, 2000],
];

export function PenFields({ pen, mount, penTypes = [], onChange }: {
  pen: Pen; mount?: MountInfo; penTypes?: PenTypeInfo[]; onChange: (value: Pen) => void;
}) {
  const meshRequired = mount?.needs_mesh ?? pen.mount === 'rigid';
  return <>
    <div className="plotter-fields">
      <label className="plotter-field"><span>Nome da caneta</span>
        <input maxLength={60} value={pen.name} onChange={e => onChange({ ...pen, name: e.target.value })} />
      </label>
      <PenTypeSelect pen={pen} types={penTypes} onChange={onChange} />
      <Numeric label="Altura de contato Z (mm)" value={pen.z_contact} min={0.3} max={40} nullable
        onChange={z_contact => onChange({ ...pen, z_contact })} />
      {penFields(pen, mount).map(([key, label, min, max]) => <Numeric key={key} label={label} value={pen[key]} min={min} max={max}
        onChange={value => { if (value !== null) onChange({ ...pen, [key]: value }); }} />)}
    </div>
    <label className="plotter-check"><input type="checkbox" checked={pen.use_mesh || meshRequired} disabled={meshRequired}
      onChange={e => onChange({ ...pen, use_mesh: e.target.checked })} /> Usar malha de nivelamento salva
      {meshRequired ? ' (obrigatória sem mola)' : ''}</label>
    <h4>Medidas de pressão</h4>
    <p className="plotter-muted">Meça a largura de cada linha do teste e informe o par {pen.mount === 'rigid' ? 'aperto' : 'compressão'} e
      largura em mm.{pen.mount === 'rigid' ? ' Sem mola a escala anda de 0,05 em 0,05 mm.' : ''}</p>
    {pen.table.map(([depth, width], index) => <div className="plotter-measure" key={index}>
      <Numeric label={pen.mount === 'rigid' ? 'Aperto' : 'Compressão'} value={depth} min={0} max={pen.max_compression} onChange={value => {
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
