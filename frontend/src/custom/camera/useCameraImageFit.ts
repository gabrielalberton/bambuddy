import { useEffect, type RefObject } from 'react';
import { displayedAspect, fitRect, rotationFromTransform } from './cameraAspect';
import { STREAM_IMG_SELECTOR } from './h264';

/** Size the unrotated image explicitly; max-size alone allows flex to shrink it before CSS rotation. */
export function useCameraImageFit(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    let last = '';
    const fit = () => {
      const img = root.current?.querySelector<HTMLImageElement>(`img[alt="Camera stream"], ${STREAM_IMG_SELECTOR}`);
      const box = img?.parentElement;
      if (!img || !box) return;
      const rotation = rotationFromTransform(img.style.transform);
      const aspect = displayedAspect(img.naturalWidth, img.naturalHeight, rotation);
      if (!aspect || !box.clientWidth || !box.clientHeight) return;
      const shown = fitRect(box.clientWidth, box.clientHeight, aspect);
      const sideways = rotation % 180 !== 0;
      const w = sideways ? shown.height : shown.width;
      const h = sideways ? shown.width : shown.height;
      const key = `${w}:${h}`;
      if (key === last && img.style.getPropertyValue('width') === `${w}px` && img.style.getPropertyPriority('max-width') === 'important') return;
      last = key;
      img.style.setProperty('width', `${w}px`, 'important');
      img.style.setProperty('height', `${h}px`, 'important');
      img.style.setProperty('max-width', 'none', 'important');
      img.style.setProperty('max-height', 'none', 'important');
      img.style.setProperty('flex', 'none', 'important');
    };
    fit();
    // Also catches MJPEG first frame (load is not reliable), reconnects and rotation changes.
    const timer = window.setInterval(fit, 120);
    return () => window.clearInterval(timer);
  }, [root]);
}
