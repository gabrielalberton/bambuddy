import { describe, expect, it } from 'vitest';
import JSZip from 'jszip';
import { asModelPackage } from '../modelPreview/packageUpload';

async function makeZip(entries: string[], name: string): Promise<File> {
  const zip = new JSZip();
  for (const entry of entries) zip.file(entry, '<fixture/>');
  const buffer = await zip.generateAsync({ type: 'arraybuffer' });
  const file = new File([buffer], name, { type: 'application/zip' });
  Object.defineProperty(file, 'arrayBuffer', { value: async () => buffer });
  return file;
}

describe('3MF package upload', () => {
  it('keeps a zipped 3MF package together rather than extracting its parts', async () => {
    const file = await makeZip(
      ['[Content_Types].xml', '3D/3dmodel.model', '3D/Objects/object_1.model'],
      'Family Figurine Split.3mf.zip',
    );
    const packaged = await asModelPackage(file);
    expect(packaged.name).toBe('Family Figurine Split.3mf');
    expect(packaged.size).toBe(file.size);
  });

  it('leaves a regular ZIP containing a 3MF to the normal extraction flow', async () => {
    const file = await makeZip(['Models/part.3mf'], 'collection.zip');
    expect(await asModelPackage(file)).toBe(file);
  });
});
