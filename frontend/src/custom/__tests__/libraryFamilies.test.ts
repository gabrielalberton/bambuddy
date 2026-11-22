import { describe, expect, it } from 'vitest';
import { groupSlicedFiles } from '../libraryFamilies/group';

const file = (id: number, parent?: number, folder = 1) => ({
  id, folder_id: folder, sliced_from_library_file_id: parent,
});

describe('groupSlicedFiles', () => {
  it('puts slices and re-slices under their original in the same folder', () => {
    const source = file(1);
    const first = file(3, 1);
    const reslice = file(6, 3);
    const unrelated = file(2);
    expect(groupSlicedFiles([reslice, unrelated, source, first])).toEqual([
      { source: unrelated, slices: [] },
      { source, slices: [reslice, first] },
    ]);
  });

  it('keeps files visible when the parent is filtered out, moved, or invalid', () => {
    const source = file(1);
    const moved = file(3, 1, 2);
    const missing = file(4, 2);
    const cycle = file(5, 5);
    expect(groupSlicedFiles([source, moved, missing, cycle])).toEqual(
      [source, moved, missing, cycle].map((entry) => ({ source: entry, slices: [] })),
    );
  });
});
