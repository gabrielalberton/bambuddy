import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';

type GridShape = { columns: number; gap: string };

/** Column count (from the resolved track list) and column gap of a CSS grid. */
function gridShape(grid: Element): GridShape {
  const style = getComputedStyle(grid);
  return {
    columns: Math.max(1, style.gridTemplateColumns.split(' ').filter(Boolean).length),
    gap: /^\d/.test(style.columnGap) ? style.columnGap : '',
  };
}

// The family spans as many library columns as it has files, never more than
// the grid has (a wider span would add columns past the screen edge). The
// cards inside sit on the grid's own columns, see families.css.
export function GridFamily({ size, children }: { size: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shape, setShape] = useState<GridShape>({ columns: 1, gap: '' });
  useLayoutEffect(() => {
    const grid = ref.current?.parentElement;
    if (!grid) return;
    const measure = () => {
      const next = gridShape(grid);
      setShape((prev) => (prev.columns === next.columns && prev.gap === next.gap ? prev : next));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      className="library-file-family library-file-family--grid"
      style={{
        gridColumn: `span ${Math.min(size, shape.columns)}`,
        ...(shape.gap && { '--library-grid-gap': shape.gap }),
      } as CSSProperties}
    >
      {children}
    </div>
  );
}
