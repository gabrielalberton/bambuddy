import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Camera } from 'lucide-react';
import { plotter } from './api';

export function PlateCamera({ id }: { id: number }) {
  const [tracking, setTracking] = useState(false);
  const camera = useQuery({
    queryKey: ['custom', 'plotter', id, 'plate-camera'],
    queryFn: () => plotter.plateCamera(id),
    enabled: tracking,
    refetchInterval: query => query.state.status === 'error' ? 2000 : 160,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  const frame = camera.data;
  const matches = tracking && !camera.error && frame?.found;
  const outline = matches && frame.outline?.map(([x, y]) => `${x * 1600},${y * 900}`).join(' ');

  return <section className="plotter-camera" aria-label="Câmera do prato">
    <button type="button" aria-expanded={tracking} onClick={() => setTracking(active => !active)}>
      <Camera size={16} aria-hidden="true" /> {tracking ? 'Fechar câmera' : 'Rastrear prato pela câmera'}
    </button>
    {tracking && <>
      {frame && <div className="plotter-camera-frame">
        <img src={`data:image/jpeg;base64,${frame.image}`} alt="Vista da Bambu Lab A1" />
        {!!outline && <svg viewBox="0 0 1600 900" aria-hidden="true">
          <polygon points={outline} vectorEffect="non-scaling-stroke" />
        </svg>}
      </div>}
      <p role="status">
        {camera.error ? camera.error.message : !frame ? 'Abrindo câmera…'
          : matches ? frame.y_mm === undefined ? 'Área útil estimada' : `Área útil estimada · Y ${frame.y_mm.toFixed(1)} mm`
          : frame.reason === 'camera_alignment' ? 'Enquadramento diferente do perfil da câmera.'
          : 'Prato sem correspondência confiável.'}
      </p>
    </>}
  </section>;
}
