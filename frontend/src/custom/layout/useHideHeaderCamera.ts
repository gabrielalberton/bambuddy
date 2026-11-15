import { useSinglePrinter } from '../useSinglePrinter';
import { inlineCameraEnabled } from '../camera/inlineCameraStore';

/**
 * Modo impressora única com a câmera embutida no card: o botão de câmera do cabeçalho compacto é redundante e some.
 * Com `custom.inlineCamera = 'off'` ele volta (aí é o único jeito de abrir a câmera).
 */
export function useHideHeaderCamera(): boolean {
  const { single } = useSinglePrinter();
  return single && inlineCameraEnabled();
}
