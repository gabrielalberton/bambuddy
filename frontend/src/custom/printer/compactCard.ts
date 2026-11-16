import './compactCard.css';

/**
 * Card compacto (modo impressora única). Mostra só o que pede atenção ou ação agora:
 *  - selos de saúde (conexão, HMS, detecção por IA, manutenção, firmware) só quando há problema;
 *  - diâmetro do bico no rótulo do tile "Bico" (não é alerta);
 *  - ventiladores só imprimindo ou girando; sem o título "Controles" e sem a luz duplicada (fica na barra da câmera);
 *  - parada: mover e verificação de placa. Imprimindo: velocidade, Pausar e Parar.
 * Desligar no navegador: localStorage.setItem('custom.compactCard', 'off')
 */
export function compactCard(single: boolean): boolean {
  if (!single) return false;
  try {
    return localStorage.getItem('custom.compactCard') !== 'off';
  } catch {
    return true;
  }
}

export function isPrintingState(state: string | null | undefined): boolean {
  return state === 'RUNNING' || state === 'PAUSE';
}
