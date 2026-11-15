import { lazy, Suspense, type ReactNode } from 'react';
import { CameraPreview } from '../camera/CameraPreview';
import { FillParentHeight } from '../camera/FillParentHeight';
import { TwinFrame } from './TwinFrame';
import { TwinSwitch } from './TwinSwitch';
import { useTwinActive, useTwinAvailable } from './useTwinView';

// three.js + motor só são baixados quando o 3D é escolhido (a tela da câmera não fica mais pesada).
const DigitalTwinView = lazy(() => import('./DigitalTwinView'));

export interface CameraOrTwinProps {
  printerId: number;
  /** classes do quadro do twin (ocupa o lugar do quadro de vídeo que ele substitui) */
  className?: string;
  /**
   * Onde fica a chave "Câmera | 3D" (sempre embaixo, ao alcance do polegar):
   * 'viewport' = fixa no rodapé da tela (página da câmera, tela cheia no celular/PWA);
   * 'frame' = no rodapé do quadro posicionado mais próximo (janela flutuante do visualizador embutido).
   */
  switchPlacement?: 'viewport' | 'frame';
  /** o quadro de vídeo original do upstream (desmontado no modo 3D: o stream da câmera fecha) */
  children: ReactNode;
}

/** Mostra o vídeo da câmera (filhos) ou, com a chave em "3D", o gêmeo digital no mesmo quadro. */
export function CameraOrTwin({ printerId, className = 'relative w-full h-full', switchPlacement = 'frame', children }: CameraOrTwinProps) {
  const available = useTwinAvailable(printerId);
  const active = useTwinActive(printerId);
  // Prévia instantânea da câmera (custom/docs/camera-previa.md): vale com ou sem o gêmeo digital.
  // Página da câmera (chave fixa na tela): o quadro de vídeo ganha altura medida (ver FillParentHeight).
  const camera = switchPlacement === 'viewport' ? <FillParentHeight>{children}</FillParentHeight> : children;
  if (!available) return <>{camera}<CameraPreview printerId={printerId} /></>;
  const pos = switchPlacement === 'viewport' ? 'fixed' : 'absolute';
  const overlay = (
    <div
      className={`${pos} left-1/2 -translate-x-1/2 z-30`}
      style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 12px)' }}
    >
      <TwinSwitch printerId={printerId} className="shadow-lg backdrop-blur-sm" />
    </div>
  );
  // `contents`: no modo câmera o quadro do upstream fica exatamente como era (sem caixa extra em volta)
  return (
    <div className="contents">
      {active ? (
        <TwinFrame printerId={printerId} className={className}>
          <Suspense fallback={null}>
            <DigitalTwinView printerId={printerId} />
          </Suspense>
        </TwinFrame>
      ) : (
        <>
          {camera}
          <CameraPreview printerId={printerId} />
        </>
      )}
      {overlay}
    </div>
  );
}
