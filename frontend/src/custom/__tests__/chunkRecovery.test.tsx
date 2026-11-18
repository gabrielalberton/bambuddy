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
    render(<ChunkErrorFallback />);
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
