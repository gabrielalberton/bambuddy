import { useLayoutEffect, useRef } from 'react';
import type { MouseEventHandler, ReactNode } from 'react';
import { isEditUserOverlayEnabled } from '../flags';
import './editUserOverlay.css';

interface EditUserOverlayProps {
  children: ReactNode;
  onClick: MouseEventHandler<HTMLDivElement>;
}

export function EditUserOverlay({ children, onClick }: EditUserOverlayProps) {
  const overlay = useRef<HTMLDivElement>(null);
  const enabled = isEditUserOverlayEnabled();

  useLayoutEffect(() => {
    const element = overlay.current;
    const viewport = window.visualViewport;
    if (!enabled || !element || !viewport) return;

    // Android Chrome can shrink or pan the visible viewport for the keyboard
    // while leaving the layout viewport (and fixed elements) unchanged.
    const updateViewport = () => {
      element.style.setProperty('--edit-user-top', `${viewport.offsetTop}px`);
      element.style.setProperty('--edit-user-height', `${viewport.height}px`);
    };

    updateViewport();
    viewport.addEventListener('resize', updateViewport);
    viewport.addEventListener('scroll', updateViewport);
    return () => {
      viewport.removeEventListener('resize', updateViewport);
      viewport.removeEventListener('scroll', updateViewport);
    };
  }, [enabled]);

  return (
    <div
      ref={overlay}
      className={enabled ? 'edit-user-overlay' : 'fixed inset-0 bg-black flex items-center justify-center z-50 p-4'}
      onClick={onClick}
    >
      {children}
    </div>
  );
}
