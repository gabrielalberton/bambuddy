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

const pt = () =>
  [document.documentElement.lang, (() => { try { return localStorage.getItem('i18nextLng'); } catch { return null; } })(), navigator.language]
    .some((l) => (l || '').toLowerCase().startsWith('pt'));

const HARD_KEY = 'custom_chunk_hard_reload_at';
const HARD_WINDOW_MS = 60_000;

/** Limpa o cache do service worker e recarrega. O SW guarda /assets para sempre (cache-first): um arquivo que
 *  ficou guardado corrompido (download cortado no celular) quebra a mesma tela em toda recarga comum. */
export async function hardReload(): Promise<void> {
  try {
    sessionStorage.setItem(HARD_KEY, String(Date.now()));
  } catch {
    /* sem sessionStorage: segue */
  }
  try {
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    const regs = (await navigator.serviceWorker?.getRegistrations?.()) ?? [];
    await Promise.all(regs.map((r) => r.unregister()));
  } catch {
    /* melhor esforço */
  }
  window.location.reload();
}

function hardReloadedRecently(): boolean {
  try {
    const last = Number(sessionStorage.getItem(HARD_KEY));
    return Boolean(last) && Date.now() - last < HARD_WINDOW_MS;
  } catch {
    return true;
  }
}

/** Tela mostrada no lugar do "UI Crash" quando o erro é de carregamento de arquivo. */
export function ChunkErrorFallback({ error }: { error?: Error | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    recoverFromMissingChunk().then((reloading) => {
      if (!alive || reloading) return;
      // A recarga comum não resolveu: limpa o cache do SW e tenta mais uma vez antes de desistir.
      if (!hardReloadedRecently()) void hardReload();
      else setFailed(true);
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
          onClick={() => void hardReload()}
          style={{ padding: '10px 18px', backgroundColor: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8, fontSize: 15 }}
        >
          {isPt ? 'Recarregar' : 'Reload'}
        </button>
      )}
      {failed && error?.message && (
        <pre style={{ marginTop: 16, fontSize: 11, color: '#71717a', whiteSpace: 'pre-wrap' }}>{error.message}</pre>
      )}
    </div>
  );
}

let installed = false;

/** Recupera falhas de import dinâmico que não passam pelo ErrorBoundary. */
export function installChunkRecovery(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  // Sem preventDefault: com ele o __vitePreload engole o erro e o import() resolve `undefined`
  // ("Cannot read properties of undefined (reading 'SettingsPage')"). O erro tem que seguir para o lazyPage.
  window.addEventListener('vite:preloadError', () => {
    void recoverFromMissingChunk();
  });
  window.addEventListener('unhandledrejection', (event) => {
    if (isChunkLoadError(event.reason)) void recoverFromMissingChunk();
  });
}

installChunkRecovery();
