import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { Video } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { cameraAspect } from './cameraAspect';
import { inlineCameraEnabled, registerInlineCamera } from './inlineCameraStore';
import './inlineCamera.css';

const EmbeddedCameraViewer = lazy(async () => ({
  default: (await import('../../components/EmbeddedCameraViewer')).EmbeddedCameraViewer,
}));

/** Cabeçalho de botões do upstream (40 px) + borda. */
const CHROME_PX = 42;
const HIDDEN_KEY = 'custom.inlineCamera.hidden';

function readHidden(id: number): boolean {
  try {
    return localStorage.getItem(`${HIDDEN_KEY}.${id}`) === '1';
  } catch {
    return false;
  }
}

function writeHidden(id: number, hidden: boolean) {
  try {
    if (hidden) localStorage.setItem(`${HIDDEN_KEY}.${id}`, '1');
    else localStorage.removeItem(`${HIDDEN_KEY}.${id}`);
  } catch {
    // ignora
  }
}

/**
 * Modo impressora única: a câmera (com a barra de botões e a chave Câmera | 3D) fica no próprio card, logo abaixo do
 * status, no lugar da janela flutuante. Reaproveita o EmbeddedCameraViewer do upstream inteiro; o CSS só o tira do
 * `position: fixed`. A altura segue a proporção da imagem (sem faixas pretas). O X recolhe para um botão.
 */
export function InlineCamera({ printerId, rotation }: { printerId: number; printerName?: string; rotation?: number | null }) {
  const { hasPermission } = useAuth();
  const allowed = inlineCameraEnabled() && hasPermission('camera:view');
  const [hidden, setHidden] = useState(() => readHidden(printerId));
  const boxRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const sideways = (((rotation ?? 0) % 360) + 360) % 180 === 90;
  const [aspect, setAspect] = useState(() => cameraAspect(printerId) ?? (sideways ? 9 / 16 : 16 / 9));

  useEffect(() => {
    if (!allowed || hidden) return;
    return registerInlineCamera(printerId);
  }, [allowed, hidden, printerId]);

  useEffect(() => {
    if (!allowed || hidden) return;
    const id = window.setInterval(() => {
      const next = cameraAspect(printerId);
      if (next) setAspect((prev) => (Math.abs(prev - next) > 0.001 ? next : prev));
    }, 1000);
    return () => window.clearInterval(id);
  }, [allowed, hidden, printerId]);

  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [allowed, hidden]);

  if (!allowed) return null;

  if (hidden) {
    return (
      <button
        type="button"
        className="mb-3 flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-bambu-dark text-sm text-bambu-gray hover:text-white"
        onClick={() => {
          writeHidden(printerId, false);
          setHidden(false);
        }}
      >
        <Video className="h-4 w-4" aria-hidden="true" />
        Câmera
      </button>
    );
  }

  const maxHeight = Math.max(240, (typeof window !== 'undefined' ? window.innerHeight : 800) - 120);
  const height = width > 0 ? Math.min(maxHeight, Math.round((width - 2) / aspect + CHROME_PX)) : 0;

  return (
    <div
      ref={boxRef}
      data-custom-inline-camera=""
      // no-drag: o cabeçalho do upstream não arrasta (nem bloqueia a rolagem da página no toque)
      className="no-drag relative mb-3 w-full overflow-hidden rounded-lg"
      style={{ height: height || undefined, minHeight: height ? undefined : 200, '--camera-split-height': `${Math.round((width - 6) / (2 * aspect) + CHROME_PX)}px` } as CSSProperties}
    >
      {width > 0 && (
        <Suspense fallback={null}>
          <EmbeddedCameraViewer
            printerId={printerId}
            // nome da impressora não aparece embutido (modo impressora única: o card já é dela)
            printerName=""
            onClose={() => {
              writeHidden(printerId, true);
              setHidden(true);
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
