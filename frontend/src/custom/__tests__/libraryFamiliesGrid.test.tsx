import { render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LibraryFileListItem } from '../../api/client';
import { renderLibraryFamilies } from '../libraryFamilies/render';
import { installMemoryStorage } from './fixtures';

const file = (id: number, parent?: number) =>
  ({ id, folder_id: 1, sliced_from_library_file_id: parent ?? null, filename: `f${id}` }) as unknown as LibraryFileListItem;

function renderGrid(files: LibraryFileListItem[]) {
  const { container } = render(
    <div>{renderLibraryFamilies(files, 'grid', (f) => <div key={f.id} data-file={f.id} />)}</div>,
  );
  return container;
}

const ids = (root: Element | null, selector: string) =>
  [...(root?.querySelectorAll(selector) ?? [])].map((e) => e.getAttribute('data-file'));

describe('famílias na grade da biblioteca', () => {
  afterEach(() => localStorage.removeItem('custom.libraryFamilies'));

  it('mostra a origem e, abaixo dela, os fatiados aninhados', () => {
    installMemoryStorage();
    const container = renderGrid([file(1), file(2, 1), file(3, 1), file(4)]);
    const family = container.querySelector('.library-file-family--grid');
    expect(family?.firstElementChild?.getAttribute('data-file')).toBe('1');
    expect(ids(family, '.library-file-family__slices > [data-file]')).toEqual(['2', '3']);
    expect([...container.firstElementChild!.children].map((e) => e.getAttribute('data-file'))).toEqual([null, '4']);
  });

  it('desligada, mostra os arquivos soltos', () => {
    installMemoryStorage();
    localStorage.setItem('custom.libraryFamilies', 'off');
    const container = renderGrid([file(1), file(2, 1)]);
    expect(container.querySelector('.library-file-family')).toBeNull();
    expect(container.querySelectorAll('[data-file]')).toHaveLength(2);
  });
});
