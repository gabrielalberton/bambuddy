import * as THREE from 'three';
import { plateOpenings, platePhoto, tracePlateOutline } from '../../plate/reference.ts';

const thickness = 0.8; // mm, from the Twin's A1 CAD model

export function createPeiPlate() {
  const shape = new THREE.Shape();
  tracePlateOutline(shape);
  shape.holes = plateOpenings.map(trace => {
    const path = new THREE.Path();
    trace(path);
    return path;
  });
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, curveSegments: 16 });
  const positions = geometry.getAttribute('position');
  const uv = geometry.getAttribute('uv');
  for (let i = 0; i < positions.count; i++) {
    uv.setXY(i, positions.getX(i) / platePhoto.width, 1 - positions.getY(i) / platePhoto.height);
  }
  geometry.translate(-platePhoto.centerX, -platePhoto.centerY, 0);
  geometry.scale(platePhoto.mmPerPixelX, platePhoto.mmPerPixelY, 1);
  geometry.rotateX(Math.PI / 2);

  const surface = new THREE.MeshStandardMaterial({ color: 0xc7a36a, roughness: 0.82 });
  if (typeof document !== 'undefined') {
    surface.map = new THREE.TextureLoader().load(platePhoto.url, () => surface.color.setHex(0xffffff));
    surface.map.colorSpace = THREE.SRGBColorSpace;
    surface.map.anisotropy = 4;
  }
  const edge = new THREE.MeshStandardMaterial({ color: 0x9e7950, roughness: 0.75 });
  const sheet = new THREE.Mesh(geometry, [surface, edge]);
  sheet.name = 'textured_pei_a1';
  sheet.receiveShadow = true;
  return sheet;
}
