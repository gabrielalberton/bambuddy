import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { RotateCw, Video, X } from 'lucide-react';
import { api, withStreamToken } from '../../api/client';
import { ChamberLight } from '../../components/icons/ChamberLight';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';
import { useStreamImgRef } from '../../hooks/useStreamImgRef';

function nativeCameraEnabled() {
  try {
    return localStorage.getItem('custom.nativeCamera') !== 'off';
  } catch {
    return true;
  }
}

type Printer = { id: number; model?: string | null; external_camera_enabled?: boolean };

export function useNativeCamera(printer: Printer, allowed: boolean, closeMenu: () => void) {
  const [open, setOpen] = useState(false);
  const enabled = allowed && printer.external_camera_enabled
    && /^(?:bambu lab )?a1(?: mini)?$/i.test(printer.model ?? '')
    && nativeCameraEnabled();

  return {
    item: enabled && (
      <button
        type="button"
        className="flex min-h-11 w-full items-center gap-2 rounded-lg px-4 text-left text-sm hover:bg-bambu-dark-tertiary"
        onClick={() => {
          closeMenu();
          setOpen(true);
        }}
      >
        <Video className="h-4 w-4 shrink-0" aria-hidden="true" />
        Câmera nativa
      </button>
    ),
    dialog: enabled && open && <NativeCameraDialog printerId={printer.id} onClose={() => setOpen(false)} />,
  };
}

function NativeCameraDialog({ printerId, onClose }: { printerId: number; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const stream = useStreamImgRef(
    image,
    withStreamToken(`/api/v1/printers/${printerId}/camera/stream?native=true&fps=5&t=${attempt}`),
  );

  useEffect(() => {
    const modal = dialog.current;
    modal?.showModal();
    return () => modal?.close();
  }, []);

  return (
    <dialog
      ref={dialog}
      aria-label="Câmera nativa da A1"
      onCancel={onClose}
      className="m-auto w-[calc(100%_-_2rem)] max-w-xl rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-0 text-white backdrop:bg-black/70"
    >
      <div className="flex items-center justify-between pl-4">
        <h2 className="text-sm font-medium">Câmera nativa da A1</h2>
        <div className="flex">
          <NativeCameraLightButton printerId={printerId} />
          <button type="button" onClick={onClose} aria-label="Fechar câmera" className="grid size-11 place-items-center">
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="relative grid min-h-32 place-items-center bg-black">
        <img key={attempt} ref={stream} alt="Vídeo da câmera nativa" onError={() => setFailed(true)}
          className={failed ? 'hidden' : 'max-h-[70dvh] w-full object-contain'} />
        {failed && (
          <button type="button" className="flex min-h-11 items-center gap-2 px-3 text-sm"
            onClick={() => {
              setFailed(false);
              setAttempt(attempt + 1);
            }}>
            <RotateCw className="size-4" aria-hidden="true" />
            Tentar novamente
          </button>
        )}
      </div>
    </dialog>
  );
}

function NativeCameraLightButton({ printerId }: { printerId: number }) {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const canControl = hasPermission('printers:control');
  const queryKey = ['printerStatus', printerId];
  const { data: status } = useQuery({
    queryKey,
    queryFn: () => api.getPrinterStatus(printerId),
    enabled: canControl,
    refetchInterval: 30_000,
  });
  const light = useMutation({
    mutationFn: async (on: boolean) => {
      const result = await api.setChamberLight(printerId, on);
      if (!result.success) throw new Error(result.message);
    },
    onSuccess: (_, on) => {
      queryClient.setQueryData<typeof status>(queryKey, (current) =>
        current ? { ...current, chamber_light: on } : current,
      );
    },
    onError: (error) => showToast(error.message, 'error'),
  });
  if (!canControl) return null;

  const on = status?.chamber_light ?? false;
  const action = t(on ? 'printers.chamberLightOff' : 'printers.chamberLightOn');
  return (
    <button
      type="button"
      aria-label={t('camera.chamberLight')}
      aria-pressed={on}
      title={action}
      disabled={!status?.connected || light.isPending}
      onClick={() => light.mutate(!on)}
      className="grid size-11 place-items-center rounded-lg hover:bg-bambu-dark-tertiary disabled:opacity-50"
    >
      <ChamberLight on={on} className="size-5" />
    </button>
  );
}
