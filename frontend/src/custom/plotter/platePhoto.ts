import { plateOpenings, platePhoto, tracePlateOutline } from '../plate/reference';

export function renderPlatePhoto(ctx: CanvasRenderingContext2D, image: HTMLImageElement | null, width: number, height: number) {
  ctx.save();
  ctx.translate(width / 2, -height / 2);
  ctx.scale(platePhoto.mmPerPixelX, platePhoto.mmPerPixelY);
  ctx.translate(-platePhoto.centerX, -platePhoto.centerY);

  const outline = new Path2D();
  tracePlateOutline(outline);
  for (const trace of plateOpenings) trace(outline);
  ctx.clip(outline, 'evenodd');
  if (image) ctx.drawImage(image, 0, 0);
  else {
    ctx.fillStyle = '#c7a36a';
    ctx.fillRect(0, 0, platePhoto.width, platePhoto.height);
  }
  ctx.restore();
}
