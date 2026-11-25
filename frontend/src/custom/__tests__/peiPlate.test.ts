import { Box3, Raycaster, Vector3 } from 'three';
import { expect, it } from 'vitest';
import { platePhoto } from '../plate/reference';
// @ts-expect-error JavaScript module in the Twin engine.
import { createPeiPlate } from '../twin/engine/peiPlate.js';

it('aligns the photo, 258 mm body and three through-holes with the twin coordinates', () => {
  const sheet = createPeiPlate();
  const bounds = new Box3().setFromObject(sheet);
  expect(bounds.min.x).toBeCloseTo(-129);
  expect(bounds.max.x).toBeCloseTo(129);
  expect(bounds.min.y).toBeCloseTo(-0.8);
  expect(bounds.max.y).toBeCloseTo(0);
  expect(bounds.min.z).toBeLessThan(-129);
  expect(bounds.max.z).toBeGreaterThan(129);

  function cast(u: number, v: number) {
    const x = (u - platePhoto.centerX) * platePhoto.mmPerPixelX;
    const z = (v - platePhoto.centerY) * platePhoto.mmPerPixelY;
    return new Raycaster(new Vector3(x, 10, z), new Vector3(0, -1, 0)).intersectObject(sheet)[0];
  }
  // Rear slot, both front cutouts, and the original clipped front-left corner.
  for (const [x, y] of [[1000, 437], [1434, 1564], [1498, 1564], [650, 1565]]) {
    expect(cast(x, y)).toBeUndefined();
  }
  // Material surrounding the openings is still present, including the printed strip.
  for (const [x, y] of [[1000, 427], [1400, 1565], [1525, 1565], [1100, 1560], [450, 1000]]) {
    expect(cast(x, y)?.point.y).toBeCloseTo(0);
  }
  const ink = cast(850, 805);
  expect(ink?.uv?.x).toBeCloseTo(850 / platePhoto.width);
  expect(ink?.uv?.y).toBeCloseTo(1 - 805 / platePhoto.height);
});
