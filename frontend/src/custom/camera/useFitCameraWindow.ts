import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { cameraAspect } from './cameraAspect';

/** Altura do cabeçalho da janela flutuante (o upstream reserva `calc(100% - 40px)` para o vídeo) + borda de 1 px. */
const HEADER_PX = 40;
const BORDER_PX = 2;
/** Mesmo mínimo do upstream (a barra de ícones do cabeçalho precisa disso). */
const MIN_WIDTH = 200;
const MARGIN = 10;
const POLL_MS = 1000;

type WindowBox = { x: number; y: number; width: number; height: number };

export function fitCameraWindowEnabled(): boolean {
  try {
    if (localStorage.getItem('custom.fitCameraWindow') === 'off') return false;
  } catch {
    // sem localStorage: segue ligado
  }
  return import.meta.env.MODE !== 'test';
}

/**
 * Janela com a proporção da imagem: largura = altura do vídeo x proporção (sem faixas pretas dos lados nem em cima).
 * Se a largura ficar abaixo do mínimo do upstream, cresce a altura; se passar da tela, encolhe as duas.
 */
export function fitWindow(box: WindowBox, aspect: number, viewport: { width: number; height: number }): WindowBox {
  const maxW = Math.max(MIN_WIDTH, viewport.width - box.x - MARGIN);
  const maxVideoH = Math.max(80, viewport.height - box.y - MARGIN - HEADER_PX - BORDER_PX);
  let videoH = Math.max(1, box.height - HEADER_PX - BORDER_PX);
  let videoW = videoH * aspect;
  if (videoW + BORDER_PX < MIN_WIDTH) {
    videoW = MIN_WIDTH - BORDER_PX;
    videoH = videoW / aspect;
  }
  if (videoH > maxVideoH) {
    videoH = maxVideoH;
    videoW = videoH * aspect;
  }
  if (videoW + BORDER_PX > maxW) {
    videoW = maxW - BORDER_PX;
    videoH = videoW / aspect;
  }
  return { ...box, width: Math.round(videoW + BORDER_PX), height: Math.round(videoH + HEADER_PX + BORDER_PX) };
}

/**
 * Gancho da janela flutuante da câmera (EmbeddedCameraViewer): ajusta o tamanho para a proporção que a câmera
 * aparece na tela (com a rotação), lida de `cameraAspect` (registrada pela prévia quando o vídeo chega).
 * Arrastar o canto continua mudando o tamanho; a largura passa a seguir a altura.
 */
export function useFitCameraWindow<T extends WindowBox>(
  printerId: number,
  state: T,
  setState: Dispatch<SetStateAction<T>>,
  active: boolean,
) {
  const enabled = fitCameraWindowEnabled() && active;
  const [aspect, setAspect] = useState<number | null>(() => cameraAspect(printerId));

  useEffect(() => {
    if (!enabled) return;
    const read = () => setAspect((prev) => {
      const next = cameraAspect(printerId);
      return next && Math.abs((prev ?? 0) - next) > 0.001 ? next : prev;
    });
    read();
    const id = window.setInterval(read, POLL_MS);
    return () => window.clearInterval(id);
  }, [enabled, printerId]);

  useEffect(() => {
    if (!enabled || !aspect) return;
    const next = fitWindow(state, aspect, { width: window.innerWidth, height: window.innerHeight });
    if (Math.abs(next.width - state.width) > 1 || Math.abs(next.height - state.height) > 1) {
      setState((prev) => ({ ...prev, width: next.width, height: next.height }));
    }
  }, [enabled, aspect, state, setState]);
}
