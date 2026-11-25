import { ImageOff, X } from 'lucide-react';
import type { HistoryItem } from './api';

const when = (seconds: number) => new Date(seconds * 1000).toLocaleString('pt-BR', {
  day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
});

/** Imagens enviadas antes, da mais recente para a mais antiga: tocar reabre, × exclui. */
export function DrawingHistory({ items, current, keep, disabled, canDelete, onOpen, onDelete }: {
  items: HistoryItem[]; current?: string; keep?: number; disabled?: boolean; canDelete: boolean;
  onOpen: (item: HistoryItem) => void; onDelete: (item: HistoryItem) => void;
}) {
  if (!items.length) return null;
  return <div className="plotter-history">
    <h3>Enviadas antes <small>{items.length}{keep ? ` de até ${keep}` : ''}</small></h3>
    <ul aria-label="Histórico de imagens">
      {items.map(item => <li key={item.id} aria-current={item.id === current ? 'true' : undefined}>
        <button type="button" className="plotter-history-open" disabled={disabled} onClick={() => onOpen(item)}
          aria-label={`Abrir ${item.name}`}>
          {item.thumb ? <img src={item.thumb} alt="" /> : <span className="plotter-history-blank"><ImageOff size={20} aria-hidden="true" /></span>}
          <strong>{item.name}</strong>
          <small>{when(item.created_at)} · {item.strokes.toLocaleString('pt-BR')} traços</small>
        </button>
        {canDelete && <button type="button" className="plotter-history-delete" disabled={disabled}
          aria-label={`Excluir ${item.name}`} onClick={() => onDelete(item)}><X size={14} aria-hidden="true" /></button>}
      </li>)}
    </ul>
  </div>;
}
