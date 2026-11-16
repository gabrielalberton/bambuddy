import { Compass } from 'lucide-react';
import type { ComponentType } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { isModelCatalogEnabled } from '../flags';
import { useCatalogT } from './i18n';

export { ModelCatalog as CatalogTab } from './ModelCatalog';

/** Id da aba na página Fontes de modelos (?tab=catalog). */
export const CATALOG_TAB = 'catalog' as const;

/**
 * Gancho da ModelSourcesPage: põe a aba "Catálogo" em PRIMEIRO lugar (vira a
 * aba padrão) quando a personalização está ligada e o usuário pode ver alguma
 * fonte. Mexe na lista de abas do upstream sem que ele precise de lógica nova.
 */
export function useCatalogTab<T extends { id: string; label: string; icon: ComponentType<{ className?: string }> }>(tabs: T[]): void {
  const t = useCatalogT();
  const { hasPermission, hasAnyPermission } = useAuth();
  const visible =
    isModelCatalogEnabled() &&
    (hasPermission('makerworld:view') || hasAnyPermission('library:read_own', 'library:read_all', 'library:read'));
  if (visible && !tabs.some((tab) => tab.id === CATALOG_TAB)) {
    tabs.unshift({ id: CATALOG_TAB, label: t('tab'), icon: Compass } as unknown as T);
  }
}

/**
 * Gancho da ModelSourcesPage: com o catálogo aberto, some o título "Fontes de modelos" e a barra de abas
 * (Catálogo/MakerWorld/Manyfold) para a busca ficar no topo da tela do celular. O link do MakerWorld continua no
 * botão de importar ao lado dos filtros. localStorage `custom.catalogSourcesHeader = 'on'` traz tudo de volta.
 */
export function hideSourcesHeader(active: string | undefined): boolean {
  if (active !== CATALOG_TAB) return false;
  try {
    return localStorage.getItem('custom.catalogSourcesHeader') !== 'on';
  } catch {
    return true;
  }
}
