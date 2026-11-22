import type { Mesh, MeshStandardMaterial } from 'three';
import type { StepWorkerMesh } from '../../workers/stepPreview.worker';

export function modelPreviewEnabled(): boolean {
  try {
    return localStorage.getItem('custom.modelPreview') !== 'off';
  } catch {
    return true;
  }
}

export function modelPreviewUrl(archiveId?: number, libraryFileId?: number): string | undefined {
  if (!modelPreviewEnabled()) return;
  if (archiveId != null) return `/api/v1/custom/model-preview/archives/${archiveId}`;
  if (libraryFileId != null) return `/api/v1/custom/model-preview/library/${libraryFileId}`;
}

export async function loadModelPreview(url: string, headers: HeadersInit, signal: AbortSignal): Promise<StepWorkerMesh[] | null> {
  let response = await fetch(url, { headers, signal });
  for (let attempt = 0; response.status === 202 && attempt < 120; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    response = await fetch(url, { headers, signal });
  }
  if (response.status === 404) return null;
  if (response.status === 202 || !response.ok) throw new Error(`3MF preview: HTTP ${response.status}`);
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
  const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), '');
  const meshes: StepWorkerMesh[] = [];
  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh) return;
    const geometry = mesh.geometry.applyMatrix4(mesh.matrixWorld);
    const position = geometry.getAttribute('position');
    const normal = geometry.getAttribute('normal');
    const material = mesh.material as MeshStandardMaterial;
    meshes.push({
      positions: Float32Array.from(position.array),
      normals: normal ? Float32Array.from(normal.array) : null,
      indices: geometry.index ? Uint32Array.from(geometry.index.array) : null,
      color: material.color ? [material.color.r, material.color.g, material.color.b] : null,
    });
    geometry.dispose();
    material.dispose();
  });
  return meshes;
}
