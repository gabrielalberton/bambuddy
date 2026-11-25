// The removable PEI sheet measures 258 × 258 mm across its square body.
// The work area of the machine is 256 × 256 mm, centered on the sheet.
// Trace the supplied top-view photo in pixels so markings and openings line up
// in both the flat Plotter and the 3D Twin.
export const platePhoto = {
  url: new URL('./textured-pei-a1.jpg', import.meta.url).href,
  width: 2000,
  height: 2000,
  centerX: 1000,
  centerY: 995.5,
  mmPerPixelX: 258 / 1110,
  mmPerPixelY: 258 / 1109,
};

type Path = Pick<Path2D, 'moveTo' | 'lineTo' | 'quadraticCurveTo' | 'closePath'>;

export function tracePlateOutline(path: Path) {
  path.moveTo(445, 476);
  path.quadraticCurveTo(445, 441, 480, 441);
  path.lineTo(847, 441);
  path.quadraticCurveTo(852, 441, 856, 437);
  path.lineTo(879, 414);
  path.quadraticCurveTo(885, 407, 897, 407);
  path.lineTo(1104, 407);
  path.quadraticCurveTo(1115, 407, 1122, 414);
  path.lineTo(1145, 437);
  path.quadraticCurveTo(1149, 441, 1155, 441);
  path.lineTo(1521, 441);
  path.quadraticCurveTo(1555, 441, 1555, 476);
  path.lineTo(1555, 1559);
  path.quadraticCurveTo(1555, 1593, 1521, 1593);
  path.lineTo(810, 1593);
  path.quadraticCurveTo(799, 1593, 789, 1584);
  path.lineTo(760, 1556);
  path.quadraticCurveTo(753, 1550, 742, 1550);
  path.lineTo(480, 1550);
  path.quadraticCurveTo(445, 1550, 445, 1516);
  path.closePath();
}

export const plateOpenings: ReadonlyArray<(path: Path) => void> = [
  path => {
    path.moveTo(909, 433);
    path.lineTo(1091, 433);
    path.quadraticCurveTo(1095, 433, 1095, 437);
    path.quadraticCurveTo(1095, 441, 1091, 441);
    path.lineTo(909, 441);
    path.quadraticCurveTo(905, 441, 905, 437);
    path.quadraticCurveTo(905, 433, 909, 433);
    path.closePath();
  },
  path => {
    path.moveTo(1410, 1555);
    path.quadraticCurveTo(1410, 1549, 1416, 1549);
    path.lineTo(1441, 1549);
    path.lineTo(1470, 1579);
    path.lineTo(1416, 1579);
    path.quadraticCurveTo(1410, 1579, 1410, 1573);
    path.closePath();
  },
  path => {
    path.moveTo(1459, 1549);
    path.lineTo(1512, 1549);
    path.quadraticCurveTo(1518, 1549, 1518, 1555);
    path.lineTo(1518, 1573);
    path.quadraticCurveTo(1518, 1579, 1512, 1579);
    path.lineTo(1488, 1579);
    path.closePath();
  },
];
