export function headerStatusEnabled(): boolean {
  try {
    if (localStorage.getItem('custom.headerStatus') === 'off') return false;
  } catch {
    // segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}

/** Botão de bug report do cabeçalho compacto: escondido por padrão (`custom.bugReportButton = 'on'` traz de volta). */
export function compactBugReportHidden(): boolean {
  try {
    if (localStorage.getItem('custom.bugReportButton') === 'on') return false;
  } catch {
    // segue o padrão
  }
  return import.meta.env.MODE !== 'test';
}
