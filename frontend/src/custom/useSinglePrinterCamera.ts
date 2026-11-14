import { useLayoutEffect } from 'react';
import { useEmbeddedCameras } from '../contexts/EmbeddedCameraContext';
import { useSinglePrinter } from './useSinglePrinter';

/**
 * CameraLauncher no modo impressora única: em vez de abrir a lista de câmeras
 * (com um item só), o clique (ou o atalho de teclado, que também só faz
 * `open = true`) abre/fecha direto a câmera da impressora e fecha o menu.
 *
 * useLayoutEffect: roda antes da pintura, então o menu nunca chega a aparecer.
 */
export function useSinglePrinterCameraToggle(open: boolean, setOpen: (next: boolean) => void, enabled: boolean): void {
  const { single, printer } = useSinglePrinter({ enabled });
  const { openCameras, openEmbeddedCamera, closeEmbeddedCamera } = useEmbeddedCameras();
  const isCameraOpen = !!printer && openCameras.some((c) => c.id === printer.id);

  useLayoutEffect(() => {
    if (!open || !single || !printer) return;
    if (isCameraOpen) closeEmbeddedCamera(printer.id);
    else openEmbeddedCamera(printer.id, printer.name, 'app');
    setOpen(false);
    // Só reage à abertura; o estado da câmera é lido no momento do clique.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, single, printer]);
}
