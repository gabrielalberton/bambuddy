import { api } from '../../api/client';
import type { PlateMetadata } from '../../types/plates';
import { isSlicedFile } from '../../utils/slicer';
import { modelPreviewEnabled } from './preview';

type Archive = Parameters<typeof isSlicedFile>[0] & { id: number };
type PreviewTarget =
  | { kind: 'geometry' | 'no-gcode' | 'gcode' }
  | { kind: 'choose-plate'; plates: PlateMetadata[] };

export async function archivePreviewTarget(archive: Archive): Promise<PreviewTarget> {
  const plates = await api.getArchivePlates(archive.id).catch(() => null);
  if (!(plates?.has_gcode ?? isSlicedFile(archive))) {
    return { kind: modelPreviewEnabled() ? 'geometry' : 'no-gcode' };
  }
  if (plates?.is_multi_plate && plates.plates.length > 1) {
    return { kind: 'choose-plate', plates: plates.plates };
  }
  return { kind: 'gcode' };
}
