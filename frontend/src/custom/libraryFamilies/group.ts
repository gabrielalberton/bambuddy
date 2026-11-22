import type { LibraryFileListItem } from '../../api/client';

export type FamilyFile = Pick<LibraryFileListItem, 'id' | 'folder_id' | 'sliced_from_library_file_id'>;
type Family<T> = { source: T; slices: T[] };

export function groupSlicedFiles<T extends FamilyFile>(files: T[]): Family<T>[] {
  const byId = new Map(files.map((file) => [file.id, file]));
  const sourceOf = (file: T): T | undefined => {
    const source = file.sliced_from_library_file_id == null
      ? undefined
      : byId.get(file.sliced_from_library_file_id);
    // The original exists before the slice. Keep missing, filtered, moved
    // and malformed relationships visible as standalone files.
    return source && source.id < file.id && source.folder_id === file.folder_id ? source : undefined;
  };

  const families = new Map<number, Family<T>>();
  for (const file of files) {
    let source = file;
    while (true) {
      const parent = sourceOf(source);
      if (!parent) break;
      source = parent;
    }
    let family = families.get(source.id);
    if (!family) {
      family = { source, slices: [] };
      families.set(source.id, family);
    }
    if (file.id !== source.id) family.slices.push(file);
  }
  return files.flatMap((file) => {
    const family = families.get(file.id);
    return family ? [family] : [];
  });
}
