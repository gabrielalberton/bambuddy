import { Download, Heart } from 'lucide-react';
import { CatalogImage } from './shared';
import type { CatalogCard } from './types';

/** Card de modelo da grade (busca e catálogo do autor). */
export function ModelCard({ card, compact, onOpen }: { card: CatalogCard; compact: Intl.NumberFormat; onOpen: (card: CatalogCard) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(card)}
      className="block w-full overflow-hidden rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary text-left active:border-bambu-green focus-visible:outline focus-visible:outline-2 focus-visible:outline-bambu-green md:hover:border-bambu-green"
    >
      <div className="aspect-square overflow-hidden bg-bambu-dark">
        <CatalogImage source={card.provider} url={card.thumbnail} alt="" className="h-full w-full object-cover" />
      </div>
      <div className="p-2.5">
        <h3 className="line-clamp-2 break-words text-sm font-semibold leading-snug text-white">{card.title}</h3>
        <p className="mt-1 truncate text-xs text-bambu-gray">{card.creator}</p>
        <div className="mt-1.5 flex gap-3 text-xs text-bambu-gray">
          {card.downloads != null && (
            <span className="flex items-center gap-1">
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              {compact.format(card.downloads)}
            </span>
          )}
          {card.likes != null && (
            <span className="flex items-center gap-1">
              <Heart className="h-3.5 w-3.5" aria-hidden="true" />
              {compact.format(card.likes)}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}
