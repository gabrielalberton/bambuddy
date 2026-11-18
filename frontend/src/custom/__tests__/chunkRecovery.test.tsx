import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../utils/lazyPage', () => ({ recoverFromMissingChunk: vi.fn(() => Promise.resolve(false)) }));

import { ChunkErrorFallback, isChunkLoadError } from '../app/chunkRecovery';

describe('custom chunk recovery', () => {
  it('reconhece erros de carregamento de arquivo', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: https://x/assets/SettingsPage-CS_bJe1x.js'))).toBe(true);
    expect(isChunkLoadError(new TypeError('Importing a module script failed.'))).toBe(true);
    expect(isChunkLoadError(new Error('Unable to preload CSS for /assets/a.css'))).toBe(true);
    expect(isChunkLoadError(new TypeError("Cannot read properties of undefined (reading 'x')"))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
  });

  it('mostra botão de recarregar quando a recuperação automática não resolve', async () => {
    sessionStorage.setItem('custom_chunk_hard_reload_at', String(Date.now())); // limpeza de cache já tentada
    render(<ChunkErrorFallback error={new TypeError('Failed to fetch dynamically imported module: x.js')} />);
    expect(await screen.findByRole('button')).toBeTruthy();
  });
});

describe('vite:preloadError', () => {
  it('não cancela o evento (senão o import resolve undefined)', async () => {
    const { installChunkRecovery } = await import('../app/chunkRecovery');
    installChunkRecovery();
    const ev = new Event('vite:preloadError', { cancelable: true });
    window.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });
});

describe('hardReload', () => {
  it('limpa caches e desregistra o service worker antes de recarregar', async () => {
    const del = vi.fn(() => Promise.resolve(true));
    vi.stubGlobal('caches', { keys: () => Promise.resolve(['a', 'b']), delete: del });
    const unregister = vi.fn(() => Promise.resolve(true));
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: () => Promise.resolve([{ unregister }]) },
    });
    const reload = vi.fn();
    Object.defineProperty(window, 'location', { configurable: true, value: { ...window.location, reload } });
    const { hardReload } = await import('../app/chunkRecovery');
    await hardReload();
    expect(del).toHaveBeenCalledTimes(2);
    expect(unregister).toHaveBeenCalled();
    expect(reload).toHaveBeenCalled();
  });
});

describe('SyntaxError de arquivo corrompido', () => {
  it('conta como falha de carregamento, menos JSON', () => {
    expect(isChunkLoadError(new SyntaxError("Unexpected token ';'"))).toBe(true);
    expect(isChunkLoadError(new SyntaxError('Unexpected end of input'))).toBe(true);
    expect(isChunkLoadError(new SyntaxError('Unexpected token < in JSON at position 0'))).toBe(false);
  });
});
