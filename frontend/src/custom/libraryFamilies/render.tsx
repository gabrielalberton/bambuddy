import { Fragment, type ReactNode } from 'react';
import type { LibraryFileListItem } from '../../api/client';
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
  return groupSlicedFiles(files).map(({ source, slices }) => slices.length ? (
    <div key={source.id} className={`library-file-family library-file-family--${layout}`}>
      {renderFile(source)}
      <div className="library-file-family__slices">
        {slices.map((slice) => <Fragment key={slice.id}>{renderFile(slice)}</Fragment>)}
      </div>
    </div>
  ) : renderFile(source));
}
