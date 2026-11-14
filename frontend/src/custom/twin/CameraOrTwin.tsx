import { lazy, Suspense, type ReactNode } from 'react';
import { useTwinActive } from './useTwinView';

// three.js + motor só são baixados quando o 3D é escolhido (a tela da câmera não fica mais pesada).
const DigitalTwinView = lazy(() => import('./DigitalTwinView'));

export interface CameraOrTwinProps {
  printerId: number;
  /** classes do quadro do twin (o mesmo tamanho do quadro de vídeo que ele substitui) */
  className?: string;
  /** o quadro de vídeo original do upstream (desmontado no modo 3D: o stream da câmera fecha) */
  children: ReactNode;
}

/** Mostra o vídeo da câmera (filhos) ou, com a chave em "3D", o gêmeo digital no mesmo quadro. */
export function CameraOrTwin({ printerId, className = 'relative w-full h-full', children }: CameraOrTwinProps) {
  const active = useTwinActive(printerId);
  if (!active) return <>{children}</>;
  return (
    <div className={`${className} bg-[#171a21]`}>
      <Suspense fallback={null}>
        <DigitalTwinView printerId={printerId} />
      </Suspense>
    </div>
  );
}
