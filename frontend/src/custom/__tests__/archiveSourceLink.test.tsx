import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../__tests__/utils';
import { MakerworldSourceLink, catalogPathForMakerworld } from '../archives/SourceLink';

describe('Origem MakerWorld no detalhe do arquivo', () => {
  it('leva ao catálogo interno', () => {
    expect(catalogPathForMakerworld('https://makerworld.com/en/models/1234567-quality-spool?from=search#profileId-99')).toBe(
      '/model-sources?tab=catalog&model=1234567&msrc=makerworld',
    );
    render(<MakerworldSourceLink url="https://makerworld.com/models/42" />);
    const a = screen.getByText('MakerWorld').closest('a')!;
    expect(a.getAttribute('href')).toBe('/model-sources?tab=catalog&model=42&msrc=makerworld');
    expect(a.getAttribute('target')).toBeNull();
  });

  it('link que não é de modelo continua externo', () => {
    render(<MakerworldSourceLink url="https://makerworld.com/en/@alguem" />);
    expect(screen.getByText('MakerWorld').closest('a')!.getAttribute('target')).toBe('_blank');
  });
});
