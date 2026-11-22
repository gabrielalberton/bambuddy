import { lazy, Suspense } from 'react';

const Viewer = lazy(async () => ({
  default: (await import('../../components/ModelViewerModal')).ModelViewerModal,
}));

export function ArchiveGeometryPreview({ archiveId, title, onClose }: {
  archiveId: number;
  title: string;
  onClose: () => void;
}) {
  return (
    <Suspense fallback={null}>
      <Viewer archiveId={archiveId} title={title} fileType="3mf" onClose={onClose} />
    </Suspense>
  );
}
