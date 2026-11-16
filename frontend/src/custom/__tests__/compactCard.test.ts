import { afterEach, describe, expect, it } from 'vitest';
import { compactCard, isPrintingState } from '../printer/compactCard';
import { installMemoryStorage } from './fixtures';

describe('card compacto', () => {
  afterEach(() => localStorage.removeItem('custom.compactCard'));

  it('só vale no modo impressora única e pode ser desligado', () => {
    installMemoryStorage();
    expect(compactCard(false)).toBe(false);
    expect(compactCard(true)).toBe(true);
    localStorage.setItem('custom.compactCard', 'off');
    expect(compactCard(true)).toBe(false);
  });

  it('imprimindo = RUNNING ou PAUSE', () => {
    expect(isPrintingState('RUNNING')).toBe(true);
    expect(isPrintingState('PAUSE')).toBe(true);
    expect(isPrintingState('FINISH')).toBe(false);
    expect(isPrintingState(undefined)).toBe(false);
  });
});
