import { lazy, Suspense, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft } from 'lucide-react';
import { CameraPreview } from '../camera/CameraPreview';
import { H264Live } from '../camera/H264Live';
import { SCOPE_ATTR } from '../camera/h264';
import { FillParentHeight } from '../camera/FillParentHeight';
import { useCameraImageFit } from '../camera/useCameraImageFit';
import { useTwinAvailable } from './useTwinView';
import './cameraPair.css';

const DigitalTwinView = lazy(() => import('./DigitalTwinView'));

export interface CameraOrTwinProps {
  printerId: number;
  className?: string;
  switchPlacement?: 'viewport' | 'frame';
  children: ReactNode;
}

/** Both viewers stay mounted: expansion and PiP only change their layout. */
export function CameraOrTwin({ printerId, className = 'relative w-full h-full', switchPlacement = 'frame', children }: CameraOrTwinProps) {
  const available = useTwinAvailable(printerId);
  const [main, setMain] = useState<'camera' | 'twin' | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useCameraImageFit(root);
  const select = (mode: 'camera' | 'twin') => (e: React.MouseEvent) => {
    e.stopPropagation();
    setMain(mode);
  };
  const content = available ? (
    <div className={`custom-camera-pair ${className}`} data-layout={main ?? 'split'} data-testid="camera-pair">
      <div className="custom-camera-pane" data-pane="camera">
        {children}
        <CameraPreview printerId={printerId} />
        <H264Live printerId={printerId} />
        {main !== 'camera' && <button type="button" className="custom-pane-select" aria-label={main ? 'Ampliar câmera e trocar com 3D' : 'Ampliar câmera'} onClick={select('camera')}><span>Câmera</span></button>}
      </div>
      <div className="custom-camera-pane" data-pane="twin">
        <Suspense fallback={<div className="p-4 text-xs text-bambu-gray">Carregando 3D…</div>}>
          <DigitalTwinView printerId={printerId} />
        </Suspense>
        {main !== 'twin' && <button type="button" className="custom-pane-select" aria-label={main ? 'Ampliar 3D e trocar com câmera' : 'Ampliar 3D'} onClick={select('twin')}><span>3D</span></button>}
      </div>
      {main && <button type="button" className="custom-pair-back" aria-label="Voltar às duas visualizações" onClick={(e) => { e.stopPropagation(); setMain(null); }}><ArrowLeft className="h-5 w-5" /></button>}
    </div>
  ) : <>{children}<CameraPreview printerId={printerId} /><H264Live printerId={printerId} /></>;
  // SCOPE_ATTR: o gancho do useStreamImgRef só reserva para o H.264 um <img> dentro deste contêiner (há um H264Live aqui)
  return <div ref={root} className="contents" {...{ [SCOPE_ATTR]: printerId }}>{switchPlacement === 'viewport' ? <FillParentHeight>{content}</FillParentHeight> : content}</div>;
}
