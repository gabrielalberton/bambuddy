import './compactMaintenance.css';

/**
 * Cards de manutenção compactos (uma linha por item: ícone, nome + barra + status, interruptor e "Redefinir" só com
 * o ícone, à direita). Só CSS sobre o card do upstream. `localStorage['custom.compactMaintenance'] = 'off'` desliga.
 */
export function compactMaintenance(): boolean {
  try {
    if (localStorage.getItem('custom.compactMaintenance') === 'off') return false;
  } catch {
    // segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}
