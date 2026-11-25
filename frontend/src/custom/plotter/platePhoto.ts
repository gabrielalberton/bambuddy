import { plateOpenings, platePhoto, tracePlateOutline } from '../plate/reference';

// The tab (lip with icons) is decoration only. Every functional measure of the plotter uses the
// plain plate_w x plate_h square, so turning the sheet around never changes what can be reached.
export type PlateTab = 'none' | 'left' | 'right';
export const PLATE_TABS: ReadonlyArray<readonly [PlateTab, string]> = [['none', 'Sem aba'], ['left', 'Aba à esquerda'], ['right', 'Aba à direita']];

export function renderPlatePhoto(ctx: CanvasRenderingContext2D, image: HTMLImageElement | null, width: number, height: number, tab: PlateTab = 'none') {
  ctx.save();
  const outline = new Path2D();
  if (tab === 'none') {
    outline.moveTo(0, 0);
    outline.lineTo(width, 0);
    outline.lineTo(width, -height);
    outline.lineTo(0, -height);
    outline.closePath();
    ctx.clip(outline, 'evenodd');
  }
  ctx.translate(width / 2, -height / 2);
  ctx.scale(tab === 'left' ? -platePhoto.mmPerPixelX : platePhoto.mmPerPixelX, platePhoto.mmPerPixelY);
  ctx.translate(-platePhoto.centerX, -platePhoto.centerY);
  if (tab !== 'none') {
    tracePlateOutline(outline);
    for (const trace of plateOpenings) trace(outline);
    ctx.clip(outline, 'evenodd');
  }
  if (image) ctx.drawImage(image, 0, 0);
  else {
    ctx.fillStyle = '#c7a36a';
    ctx.fillRect(0, 0, platePhoto.width, platePhoto.height);
  }
  ctx.restore();
}
