import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cameraAspect, fitRect } from '../camera/cameraAspect';

/**
 * Quadro do gêmeo digital com o MESMO retângulo que a imagem da câmera ocupa (mesma proporção, centralizado): a troca
 * Câmera <-> 3D não muda de tamanho. Sem proporção conhecida (câmera nunca aberta neste aparelho), ocupa tudo.
 */
export function TwinFrame({ printerId, className, children }: { printerId: number; className: string; children: ReactNode }) {
  const outer = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const el = outer.current;
    const aspect = cameraAspect(printerId);
    if (!el || !aspect) return;
    const measure = () => {
      const { clientWidth: w, clientHeight: h } = el;
      setSize(w > 0 && h > 0 ? fitRect(w, h, aspect) : null);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [printerId]);
  return (
    <div ref={outer} className={`${className} relative flex items-center justify-center bg-black`}>
      <div className="relative bg-[#171a21]" style={size ?? { width: '100%', height: '100%' }}>
        {children}
      </div>
    </div>
  );
}
