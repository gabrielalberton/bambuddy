import { BadgeCheck, Calendar, Download, Heart, Printer, Star, Zap } from 'lucide-react';
import type { ComponentType } from 'react';
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

/**
 * Dados do perfil de impressão (card de perfil do Handy): autor/"Designer" com nota, filamentos
 * ("PLA | 302 g") e a linha "3.7k downloads · 1.4k impressões · Lançado … · 2 pratos · 9.7 h · 302 g · 0.4 mm".
 * Só aparece o que a fonte devolveu (hoje: MakerWorld).
 */
export function ProfileDetails({ file }: { file: CatalogFile }) {
  const t = useCatalogT();
  const m = file.metadata;
  const ratingAverage = num(m.rating_average);
  const ratingCount = num(m.rating_count);
  const creator = typeof m.creator === 'string' ? m.creator : null;
  const filaments = (Array.isArray(m.filaments) ? m.filaments : []) as Filament[];
  const printers = (Array.isArray(m.compatible_printers) ? m.compatible_printers : []).filter((p): p is string => typeof p === 'string');
  const downloads = num(m.downloads);
  const prints = num(m.prints);
  const plates = num(m.plate_count);
  const time = num(m.print_time_s);
  const weight = num(m.weight_g);
  const nozzle = num(m.nozzle_mm);
  const published = isoDate(typeof m.published === 'string' ? m.published : null);
  const updated = isoDate(typeof m.updated === 'string' ? m.updated : null);
  const facts = [
    downloads != null && `${compactNumber(downloads)} ${t('statDownloads')}`,
    prints != null && `${compactNumber(prints)} ${t('statPrints')}`,
    published && t('published', { date: published }),
    updated && updated !== published && t('updated', { date: updated }),
    plates != null && t('plateCount', { count: plates }),
    time != null && duration(time),
    weight != null && grams(weight),
    nozzle != null && `${nozzle} mm`,
  ].filter(Boolean) as string[];
  if (!creator && ratingAverage == null && filaments.length === 0 && facts.length === 0) return null;
  return (
    <span className="mt-1.5 block space-y-1 text-xs text-bambu-gray">
      {(creator || m.is_designer === true || ratingAverage != null) && (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {m.is_designer === true ? (
            <span className="inline-flex items-center gap-0.5 rounded bg-bambu-green/15 px-1.5 py-0.5 font-medium text-bambu-green">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {t('designer')}
            </span>
          ) : (
            creator && <span className="break-all">{t('by', { creator })}</span>
          )}
          {ratingAverage != null && ratingCount != null && ratingCount > 0 && (
            <span className="inline-flex items-center gap-0.5" aria-label={t('ratingAria', { average: ratingAverage.toFixed(1), count: ratingCount })}>
              <Star className="h-3.5 w-3.5 text-amber-400" fill="currentColor" strokeWidth={0} aria-hidden="true" />
              <span className="font-medium text-white">{ratingAverage.toFixed(1)}</span>
              <span>({compactNumber(ratingCount)})</span>
            </span>
          )}
        </span>
      )}
      {filaments.length > 0 && (
        <span className="flex flex-wrap gap-1.5">
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
      {facts.length > 0 && <span className="block">{facts.join(' · ')}</span>}
      {printers.length > 0 && <span className="line-clamp-2 block">{t('compatiblePrinters', { list: printers.join(', ') })}</span>}
    </span>
  );
}
