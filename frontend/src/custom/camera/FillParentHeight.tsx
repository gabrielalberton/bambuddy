import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

/**
 * Dá ao quadro de vídeo da página da câmera uma altura explícita (a altura útil do contêiner pai, medida).
 * Sem isso o `h-full` do quadro do upstream não resolve (o pai não tem altura "definida" para percentuais) e o quadro
 * fica com 0 px até a imagem carregar; com a câmera deitada (90/270°) o upstream dimensiona a imagem PELO quadro
 * (`useSidewaysBox`), então ela nunca aparece (impasse). Medindo o pai, o quadro tem tamanho desde o início.
 */
export function FillParentHeight({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    // o pai real (o CameraOrTwin usa `display: contents`, que não tem caixa)
    let parent = ref.current?.parentElement ?? null;
    while (parent && getComputedStyle(parent).display === 'contents') parent = parent.parentElement;
    if (!parent) return;
    const measure = () => {
      const cs = getComputedStyle(parent);
      const h = parent.clientHeight - parseFloat(cs.paddingTop || '0') - parseFloat(cs.paddingBottom || '0');
      setHeight((prev) => (h > 0 && h !== prev ? h : prev));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} className="relative w-full flex items-center justify-center" style={height ? { height } : undefined}>
      {children}
    </div>
  );
}
