/**
 * Proporção da imagem da câmera como aparece na tela (já considerando a rotação configurada no Bambuddy).
 * A prévia (CameraPreview) registra quando vê o <img> do stream; o gêmeo digital usa para ocupar exatamente o mesmo
 * retângulo que a câmera, e a troca Câmera <-> 3D não "pula" de tamanho.
 */
const KEY = 'custom.cameraAspect';

/** Rotação em graus (0/90/180/270) lida do `transform` inline do <img> do upstream (`rotate(Ndeg)`). */
export function rotationFromTransform(transform: string | null | undefined): number {
  const m = /rotate\((-?\d+(?:\.\d+)?)deg\)/.exec(transform ?? '');
  const deg = m ? Number(m[1]) : 0;
  return ((Math.round(deg / 90) * 90) % 360 + 360) % 360;
}

export function displayedAspect(width: number, height: number, rotation: number): number | null {
  if (!(width > 0 && height > 0)) return null;
  return rotation % 180 === 0 ? width / height : height / width;
}

export function rememberCameraAspect(printerId: number, aspect: number | null) {
  if (!aspect || !Number.isFinite(aspect)) return;
  try {
    const all = JSON.parse(localStorage.getItem(KEY) || '{}') as Record<string, number>;
    if (Math.abs((all[printerId] ?? 0) - aspect) < 0.001) return;
    all[printerId] = Math.round(aspect * 10000) / 10000;
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // sem localStorage: o twin ocupa o quadro inteiro
  }
}

export function cameraAspect(printerId: number): number | null {
  try {
    const v = (JSON.parse(localStorage.getItem(KEY) || '{}') as Record<string, number>)[printerId];
    return typeof v === 'number' && v > 0 ? v : null;
  } catch {
    return null;
  }
}

/** Maior retângulo com a proporção `aspect` que cabe em (w, h). */
export function fitRect(w: number, h: number, aspect: number): { width: number; height: number } {
  if (w / h > aspect) return { width: Math.round(h * aspect), height: Math.round(h) };
  return { width: Math.round(w), height: Math.round(w / aspect) };
}
