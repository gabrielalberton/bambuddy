import { useLayoutEffect, useRef, type HTMLAttributes } from 'react';
import { areScrollableModalsEnabled } from '../flags';
import './ScrollableModalOverlay.css';

interface ScrollableModalOverlayProps extends HTMLAttributes<HTMLDivElement> {
  zIndexClassName?: string;
}

/** Fixed backdrop for a single panel that may exceed the visible viewport. */
export function ScrollableModalOverlay({ children, className = '', zIndexClassName = 'z-50', ...props }: ScrollableModalOverlayProps) {
  const overlay = useRef<HTMLDivElement>(null);
  const enabled = areScrollableModalsEnabled();

  useLayoutEffect(() => {
    const element = overlay.current;
    const viewport = window.visualViewport;
    if (!enabled || !element || !viewport) return;

    // Mobile browsers can shrink or pan the visible area for the keyboard
    // without changing the layout viewport used by fixed elements.
    const updateViewport = () => {
      element.style.setProperty('--modal-top', `${viewport.offsetTop}px`);
      element.style.setProperty('--modal-height', `${viewport.height}px`);
    };

    updateViewport();
    viewport.addEventListener('resize', updateViewport);
    viewport.addEventListener('scroll', updateViewport);
    return () => {
      viewport.removeEventListener('resize', updateViewport);
      viewport.removeEventListener('scroll', updateViewport);
    };
  }, [enabled]);

  const layout = enabled ? 'scrollable-modal-overlay' : 'inset-0 flex items-center justify-center p-4';
  return (
    <div ref={overlay} className={`fixed ${layout} ${zIndexClassName} ${className}`} {...props}>
      {children}
    </div>
  );
}
