/**
 * custom(chunk-recovery): telas que falham ao carregar o arquivo (deploy novo, servidor reiniciando,
 * rede do celular oscilando) se recuperam sozinhas em vez de cair no "UI Crash".
 *
 * O upstream (lazyPage, #3175) já recarrega uma vez quando a página falha. Sobravam três buracos:
 * - o botão "Retry" do ErrorBoundary só limpava o estado, e o React.lazy guarda a promessa que
 *   falhou, então a mesma tela falhava de novo para sempre;
 * - imports dinâmicos fora do lazyPage (componentes, vite:preloadError) não tinham recuperação;
 * - a tela de erro só mostrava a stack, sem um caminho claro para sair.
 */
import { useEffect, useState } from 'react';
import { recoverFromMissingChunk } from '../../utils/lazyPage';

const CHUNK_ERROR_RE =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk [\w-]+ failed|is not a valid JavaScript MIME type/i;

export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  return CHUNK_ERROR_RE.test(message);
}

const pt = () => (document.documentElement.lang || navigator.language || '').toLowerCase().startsWith('pt');

/** Tela mostrada no lugar do "UI Crash" quando o erro é de carregamento de arquivo. */
export function ChunkErrorFallback() {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    recoverFromMissingChunk().then((reloading) => {
      if (alive && !reloading) setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, []);
  const isPt = pt();
  return (
    <div
      data-testid="custom-chunk-error"
      style={{ padding: 24, color: '#e4e4e7', backgroundColor: '#18181b', minHeight: '100vh', fontFamily: 'system-ui, sans-serif' }}
    >
      <h1 style={{ fontSize: 18, marginBottom: 8 }}>
        {failed
          ? isPt ? 'Não foi possível carregar esta tela' : 'Could not load this screen'
          : isPt ? 'Atualizando o Bambuddy…' : 'Updating Bambuddy…'}
      </h1>
      <p style={{ fontSize: 14, color: '#a1a1aa', marginBottom: 16 }}>
        {failed
          ? isPt
            ? 'A conexão caiu ou saiu uma versão nova. Recarregue para continuar.'
            : 'The connection dropped or a new version was deployed. Reload to continue.'
          : isPt
            ? 'Uma versão nova foi instalada ou o servidor está reiniciando. A página recarrega sozinha.'
            : 'A new version was installed or the server is restarting. The page reloads by itself.'}
      </p>
      {failed && (
        <button
          onClick={() => window.location.reload()}
          style={{ padding: '10px 18px', backgroundColor: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8, fontSize: 15 }}
        >
          {isPt ? 'Recarregar' : 'Reload'}
        </button>
      )}
    </div>
  );
}

let installed = false;

/** Recupera falhas de import dinâmico que não passam pelo ErrorBoundary. */
export function installChunkRecovery(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault();
    void recoverFromMissingChunk();
  });
  window.addEventListener('unhandledrejection', (event) => {
    if (isChunkLoadError(event.reason)) void recoverFromMissingChunk();
  });
}

installChunkRecovery();
