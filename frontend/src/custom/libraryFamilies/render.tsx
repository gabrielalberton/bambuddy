import { Fragment, type ReactNode } from 'react';
import type { LibraryFileListItem } from '../../api/client';
import { GridFamily } from './GridFamily';
import { groupSlicedFiles } from './group';
import './families.css';

function enabled() {
  try {
    return localStorage.getItem('custom.libraryFamilies') !== 'off';
  } catch {
    return true;
  }
}

// Every row stays visible, so keyboard focus and Select All can use the same
// ordered files that the three layouts render.
export function orderLibraryFamilies(files: LibraryFileListItem[]): LibraryFileListItem[] {
  return enabled() ? groupSlicedFiles(files).flatMap(({ source, slices }) => [source, ...slices]) : files;
}

export function renderLibraryFamilies(
  files: LibraryFileListItem[],
  layout: 'list' | 'grid' | 'columns',
  renderFile: (file: LibraryFileListItem) => ReactNode,
): ReactNode[] {
  if (!enabled()) return files.map(renderFile);
  return groupSlicedFiles(files).map(({ source, slices }) => {
    if (!slices.length) return renderFile(source);
    const content = (
      <>
        {renderFile(source)}
        <div className="library-file-family__slices">
          {slices.map((slice) => <Fragment key={slice.id}>{renderFile(slice)}</Fragment>)}
        </div>
      </>
    );
    return layout === 'grid' ? (
      <GridFamily key={source.id} size={1 + slices.length}>{content}</GridFamily>
    ) : (
      <div key={source.id} className={`library-file-family library-file-family--${layout}`}>{content}</div>
    );
  });
}
