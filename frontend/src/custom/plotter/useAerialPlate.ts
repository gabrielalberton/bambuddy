import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { plotter } from './api';

export type Aerial = { src: string; margin: number };

/** Live top-down view of the plate (lens and perspective corrected), kept on the last good frame. */
export function useAerialPlate(id: number, enabled: boolean) {
  const [aerial, setAerial] = useState<Aerial | null>(null);
  const query = useQuery({
    queryKey: ['custom', 'plotter', id, 'plate-topdown'],
    queryFn: () => plotter.plateCamera(id, true),
    enabled,
    refetchInterval: current => current.state.status === 'error' ? 2000 : 800,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  const frame = query.data;

  useEffect(() => {
    if (!enabled) setAerial(null);
    else if (frame?.found && frame.topdown) {
      setAerial({ src: `data:image/jpeg;base64,${frame.topdown.image}`, margin: frame.topdown.margin });
    }
  }, [enabled, frame]);

  const kept = aerial ? ' · mantendo a última imagem' : '';
  const status = !enabled ? ''
    : query.error ? `${query.error.message}${kept}`
    : !frame ? 'Abrindo câmera…'
    : frame.found ? 'Vista aérea ao vivo da câmera'
    : `${frame.reason === 'camera_alignment' ? 'Enquadramento diferente do perfil da câmera.' : 'Prato sem correspondência confiável.'}${kept}`;
  return { aerial, status };
}
