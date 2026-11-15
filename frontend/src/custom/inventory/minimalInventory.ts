/**
 * Estoque minimalista: sem a busca e sem a linha de filtros (Ativo/Arquivado, Usado/Novo, Estoque, Material, Marca,
 * Bobina...) e o contador de carretéis. Se algum filtro ou busca estiver ativo (estado salvo), a barra volta a
 * aparecer para dar como limpar. `localStorage['custom.minimalInventory'] = 'off'` desliga.
 */
export function minimalInventory(filtering: boolean): boolean {
  if (filtering) return false;
  try {
    if (localStorage.getItem('custom.minimalInventory') === 'off') return false;
  } catch {
    // segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}
