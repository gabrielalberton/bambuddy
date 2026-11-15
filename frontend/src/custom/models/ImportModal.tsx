import { useEffect, useRef } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Link2, X } from 'lucide-react';
import { MakerworldPage } from '../../pages/MakerworldPage';
import { useAuth } from '../../contexts/AuthContext';
import { useCatalogT } from './i18n';
import { controlClass } from './constants';

/** Parâmetro de URL do modal: abrir faz push no histórico, então o "voltar" do Android fecha. */
export const IMPORT_PARAM = 'mwimport';

/**
 * Ícone de link na linha de filtros do Catálogo que abre o "Importar do MakerWorld" (colar URL + Resolver)
 * do upstream num modal. Composição pura: o conteúdo é o próprio ``MakerworldPage embedded`` (mesma lógica,
 * mesmas permissões e importação), nada duplicado aqui.
 */
export function MakerworldImportButton() {
  const t = useCatalogT();
  const { hasPermission } = useAuth();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  if (!hasPermission('makerworld:view')) return null;
  const open = params.get(IMPORT_PARAM) === '1';
  const show = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set(IMPORT_PARAM, '1');
        return next;
      },
      { state: { [IMPORT_PARAM]: true } },
    );
  const close = () => {
    // Aberto por aqui: voltar no histórico (igual ao botão do Android). Link direto: só tira o parâmetro.
    if ((location.state as Record<string, unknown> | null)?.[IMPORT_PARAM]) navigate(-1);
    else
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete(IMPORT_PARAM);
          return next;
        },
        { replace: true },
      );
  };
  return (
    <>
      <button type="button" className={`${controlClass} ml-auto w-11 shrink-0 px-0`} onClick={show} aria-label={t('importLink')} title={t('importLink')}>
        <Link2 className="h-5 w-5" aria-hidden="true" />
      </button>
      {open && <MakerworldImportModal onClose={close} />}
    </>
  );
}

function MakerworldImportModal({ onClose }: { onClose: () => void }) {
  const t = useCatalogT();
  const closeRef = useRef<HTMLButtonElement>(null);
  // Ref: o efeito roda uma vez só (senão o foco voltaria ao "fechar" a cada render, roubando o campo de URL).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', onKey);
    };
  }, []);
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/60 md:items-center md:p-6" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="catalog-import-title"
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col bg-bambu-dark md:h-auto md:max-h-[90vh] md:max-w-3xl md:rounded-xl md:border md:border-bambu-dark-tertiary"
        style={{ paddingTop: 'env(safe-area-inset-top)', paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="flex items-center justify-between gap-2 border-b border-bambu-dark-tertiary px-4 py-2">
          <h2 id="catalog-import-title" className="flex items-center gap-2 text-base font-semibold text-white">
            <Link2 className="h-5 w-5 text-bambu-green" aria-hidden="true" />
            {t('importLink')}
          </h2>
          <button ref={closeRef} type="button" className={`${controlClass} w-11 px-0`} onClick={onClose} aria-label={t('close')}>
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <MakerworldPage embedded />
        </div>
      </div>
    </div>
  );
}
