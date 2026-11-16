import { Calendar, CircleDot, Clock, Download, Heart, Layers, Printer, Star, Weight, Zap } from 'lucide-react';
import { useMemo, type ComponentType, type ReactNode } from 'react';
import { sanitizeDescription } from './utils';
import { useCatalogT, type CatalogKey } from './i18n';
import { compactNumber, duration, grams, isoDate } from './format';
import type { CatalogFile, CatalogStats } from './types';

const STAT_ITEMS: { key: keyof CatalogStats; label: CatalogKey; icon: ComponentType<{ className?: string }> }[] = [
  { key: 'downloads', label: 'statDownloads', icon: Download },
  { key: 'prints', label: 'statPrints', icon: Printer },
  { key: 'makes', label: 'statMakes', icon: Printer },
  { key: 'likes', label: 'statLikes', icon: Heart },
  { key: 'boosts', label: 'statBoosts', icon: Zap },
];

/** Números do modelo (downloads, impressões, curtidas, impulsos, lançamento), como no topo do Handy. */
export function ModelStatsRow({ stats }: { stats: CatalogStats | undefined }) {
  const t = useCatalogT();
  if (!stats) return null;
  const items = STAT_ITEMS.filter((s) => typeof stats[s.key] === 'number');
  const published = isoDate(stats.published);
  if (items.length === 0 && !published) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-bambu-gray">
      {items.map(({ key, label, icon: Icon }) => (
        <li key={key} className="inline-flex items-center gap-1">
          <Icon className="h-4 w-4" aria-hidden="true" />
          <span className="font-medium text-white">{compactNumber(stats[key] as number)}</span>
          <span>{t(label)}</span>
        </li>
      ))}
      {published && (
        <li className="inline-flex items-center gap-1">
          <Calendar className="h-4 w-4" aria-hidden="true" />
          {t('published', { date: published })}
        </li>
      )}
    </ul>
  );
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

interface Filament {
  type: string;
  color: string | null;
  grams: number | null;
}

/** Números do perfil como ícone + número (o significado fica no title/aria-label). */
function Fact({ icon: Icon, label, children }: { icon: ComponentType<{ className?: string }>; label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1" title={label} aria-label={label}>
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span aria-hidden="true">{children}</span>
    </span>
  );
}

/**
 * Dados do perfil de impressão (card de perfil do Handy): nota, filamentos ("PLA | 302 g") e os números como
 * ícone + número (downloads, impressões, pratos, tempo, peso, bico, atualização). Sem autor nem lista de
 * impressoras (o selo "Feito para A1" já diz isso). Selecionado, mostra também o texto do autor do perfil.
 * Só aparece o que a fonte devolveu (hoje: MakerWorld).
 */
export function ProfileDetails({ file, expanded = false }: { file: CatalogFile; expanded?: boolean }) {
  const t = useCatalogT();
  const m = file.metadata;
  const ratingAverage = num(m.rating_average);
  const ratingCount = num(m.rating_count);
  const filaments = (Array.isArray(m.filaments) ? m.filaments : []) as Filament[];
  const downloads = num(m.downloads);
  const prints = num(m.prints);
  const plates = num(m.plate_count);
  const time = num(m.print_time_s);
  const weight = num(m.weight_g);
  const nozzle = num(m.nozzle_mm);
  const published = isoDate(typeof m.published === 'string' ? m.published : null);
  const updated = isoDate(typeof m.updated === 'string' ? m.updated : null);
  const date = updated ?? published;
  const summary = useMemo(
    () => (expanded && typeof m.summary_html === 'string' ? sanitizeDescription(m.summary_html) : ''),
    [expanded, m.summary_html],
  );
  const hasRating = ratingAverage != null && ratingCount != null && ratingCount > 0;
  const facts = [
    downloads != null && <Fact key="dl" icon={Download} label={`${compactNumber(downloads)} ${t('statDownloads')}`}>{compactNumber(downloads)}</Fact>,
    prints != null && <Fact key="pr" icon={Printer} label={`${compactNumber(prints)} ${t('statPrints')}`}>{compactNumber(prints)}</Fact>,
    plates != null && <Fact key="pl" icon={Layers} label={t('plateCount', { count: plates })}>{plates}</Fact>,
    time != null && <Fact key="ti" icon={Clock} label={duration(time)}>{duration(time)}</Fact>,
    weight != null && <Fact key="we" icon={Weight} label={grams(weight)}>{grams(weight)}</Fact>,
    nozzle != null && <Fact key="no" icon={CircleDot} label={`${nozzle} mm`}>{nozzle}</Fact>,
    date && <Fact key="da" icon={Calendar} label={updated ? t('updated', { date }) : t('published', { date })}>{date}</Fact>,
  ].filter(Boolean);
  if (!hasRating && filaments.length === 0 && facts.length === 0 && !summary) return null;
  return (
    <span className="mt-1.5 block space-y-1.5 text-xs text-bambu-gray">
      {(hasRating || filaments.length > 0) && (
        <span className="flex flex-wrap items-center gap-1.5">
          {hasRating && (
            <span className="inline-flex items-center gap-0.5" aria-label={t('ratingAria', { average: ratingAverage.toFixed(1), count: ratingCount })}>
              <Star className="h-3.5 w-3.5 text-amber-400" fill="currentColor" strokeWidth={0} aria-hidden="true" />
              <span className="font-medium text-white">{ratingAverage.toFixed(1)}</span>
              <span>({compactNumber(ratingCount)})</span>
            </span>
          )}
          {filaments.map((f, index) => (
            <span key={`${f.type}-${index}`} className="inline-flex items-center gap-1 rounded bg-bambu-dark-tertiary/60 px-1.5 py-0.5 text-white">
              {f.color && /^#[0-9a-fA-F]{3,8}$/.test(f.color) && (
                <span className="h-2.5 w-2.5 rounded-full border border-white/30" style={{ backgroundColor: f.color }} aria-hidden="true" />
              )}
              {f.type}
              {f.grams != null && <span className="text-bambu-gray">| {grams(f.grams)}</span>}
            </span>
          ))}
        </span>
      )}
      {facts.length > 0 && <span className="flex flex-wrap items-center gap-x-3 gap-y-1">{facts}</span>}
      {summary && (
        <span
          className="block break-words border-t border-bambu-dark-tertiary pt-1.5 text-sm leading-relaxed text-bambu-gray [&_a]:text-bambu-green [&_a]:underline [&_img]:hidden [&_li]:ml-4 [&_ol]:list-decimal [&_p]:mb-1.5 [&_strong]:text-white [&_ul]:list-disc"
          dangerouslySetInnerHTML={{ __html: summary }}
        />
      )}
    </span>
  );
}
