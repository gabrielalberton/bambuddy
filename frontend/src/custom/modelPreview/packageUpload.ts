import { modelPreviewEnabled } from './preview';

/** A 3MF package is already a ZIP. Keep its relationship entries and parts together. */
export async function asModelPackage(file: File): Promise<File> {
  if (!file.name.toLowerCase().endsWith('.zip') || !modelPreviewEnabled()) return file;
  try {
    const { default: JSZip } = await import('jszip');
    const zip = await JSZip.loadAsync(await file.arrayBuffer());
    if (zip.file('[Content_Types].xml') && zip.file('3D/3dmodel.model')) {
      const filename = file.name.slice(0, -4);
      return new File([file], filename.toLowerCase().endsWith('.3mf') ? filename : `${filename}.3mf`, {
        type: 'model/3mf',
        lastModified: file.lastModified,
      });
    }
  } catch {
    // Let the normal ZIP upload report an invalid archive.
  }
  return file;
}
