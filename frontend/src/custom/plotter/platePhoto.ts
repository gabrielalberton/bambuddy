// The square part of the reference photo maps to the 256 × 256 mm bed.
// The tabs stay visible around that square without extending the plotting area.
export function renderPlatePhoto(ctx: CanvasRenderingContext2D, image: HTMLImageElement, width: number, height: number) {
  ctx.save();
  ctx.translate(0, -height);
  ctx.scale(width / 1110, height / 1109);
  ctx.translate(-445, -441);

  const outline = new Path2D();
  outline.moveTo(445, 476);
  outline.quadraticCurveTo(445, 441, 480, 441);
  outline.lineTo(847, 441);
  outline.quadraticCurveTo(852, 441, 856, 437);
  outline.lineTo(879, 414);
  outline.quadraticCurveTo(885, 407, 897, 407);
  outline.lineTo(1104, 407);
  outline.quadraticCurveTo(1115, 407, 1122, 414);
  outline.lineTo(1145, 437);
  outline.quadraticCurveTo(1149, 441, 1155, 441);
  outline.lineTo(1521, 441);
  outline.quadraticCurveTo(1555, 441, 1555, 476);
  outline.lineTo(1555, 1559);
  outline.quadraticCurveTo(1555, 1593, 1521, 1593);
  outline.lineTo(810, 1593);
  outline.quadraticCurveTo(799, 1593, 789, 1584);
  outline.lineTo(760, 1556);
  outline.quadraticCurveTo(753, 1550, 742, 1550);
  outline.lineTo(480, 1550);
  outline.quadraticCurveTo(445, 1550, 445, 1516);
  outline.closePath();
  outline.rect(905, 433, 190, 8);
  ctx.clip(outline, 'evenodd');

  ctx.drawImage(image, 0, 0);
  ctx.restore();
}
