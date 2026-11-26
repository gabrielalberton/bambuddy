import { render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LibraryFileListItem } from '../../api/client';
import { renderLibraryFamilies } from '../libraryFamilies/render';
import { installMemoryStorage } from './fixtures';

const file = (id: number, parent?: number) =>
  ({ id, folder_id: 1, sliced_from_library_file_id: parent ?? null, filename: `f${id}` }) as unknown as LibraryFileListItem;

function renderGrid(files: LibraryFileListItem[], columns = '100px 100px') {
  const { container } = render(
    <div style={{ display: 'grid', gridTemplateColumns: columns, columnGap: '16px' }}>
      {renderLibraryFamilies(files, 'grid', (f) => <div key={f.id} data-file={f.id} />)}
    </div>,
  );
  return container;
}

describe('famílias na grade da biblioteca', () => {
  afterEach(() => localStorage.removeItem('custom.libraryFamilies'));

  it('ocupa no máximo as colunas da grade e usa o espaçamento dela', () => {
    installMemoryStorage();
    const container = renderGrid([file(1), file(2, 1), file(3, 1), file(4)]);
    const family = container.querySelector<HTMLElement>('.library-file-family--grid')!;
    expect(family.style.gridColumn).toBe('span 2');
    expect(family.style.getPropertyValue('--library-grid-gap')).toBe('16px');
    expect([...family.querySelectorAll('[data-file]')].map((e) => e.getAttribute('data-file'))).toEqual(['1', '2', '3']);
    expect(container.querySelector('[data-file="4"]')!.parentElement).toBe(family.parentElement);
  });

  it('família pequena ocupa só as colunas dos seus arquivos', () => {
    installMemoryStorage();
    const container = renderGrid([file(1), file(2, 1)], '100px 100px 100px 100px');
    expect(container.querySelector<HTMLElement>('.library-file-family--grid')!.style.gridColumn).toBe('span 2');
    const single = renderGrid([file(5)]);
    expect(single.querySelector('.library-file-family')).toBeNull();
  });

  it('desligada, mostra os arquivos soltos', () => {
    installMemoryStorage();
    localStorage.setItem('custom.libraryFamilies', 'off');
    const container = renderGrid([file(1), file(2, 1)]);
    expect(container.querySelector('.library-file-family')).toBeNull();
    expect(container.querySelectorAll('[data-file]')).toHaveLength(2);
  });
});
