import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { PlateRoiEditor } from '../plateRoi/PlateRoiEditor';
import { moveQuad, pointInQuad, quadToRoi, roiToQuad, type QuadRoi } from '../plateRoi/plateRoiGeom';

describe('geometria da área em quadrilátero', () => {
  it('migra o retângulo antigo para os 4 cantos e devolve o envolvente', () => {
    const quad = roiToQuad({ x: 0.1, y: 0.2, w: 0.5, h: 0.4 });
    expect(quad).toEqual([[0.1, 0.2], [0.6, 0.2], [0.6, 0.6000000000000001], [0.1, 0.6000000000000001]]);
    const roi = quadToRoi([[0.3, 0.4], [0.7, 0.4], [0.9, 0.9], [0.1, 0.9]]);
    expect(roi).toMatchObject({ x: 0.1, y: 0.4, w: 0.8, h: 0.5 });
    expect(roi.points).toHaveLength(4);
  });

  it('move a área inteira sem sair da imagem', () => {
    const moved = moveQuad([[0.3, 0.4], [0.7, 0.4], [0.9, 0.9], [0.1, 0.9]], 0.5, 0.5);
    expect(Math.max(...moved.map((p) => p[0]))).toBeCloseTo(1);
    expect(Math.max(...moved.map((p) => p[1]))).toBeCloseTo(1);
    expect(moved[0][0]).toBeCloseTo(0.4);
  });

  it('acerta ponto dentro e fora do trapézio', () => {
    const q = roiToQuad({ x: 0, y: 0, w: 0, h: 0, points: [[0.3, 0.4], [0.7, 0.4], [0.9, 0.9], [0.1, 0.9]] });
    expect(pointInQuad(q, [0.5, 0.6])).toBe(true);
    expect(pointInQuad(q, [0.12, 0.45])).toBe(false);
  });
});

function Harness({ onChange }: { onChange: (r: QuadRoi) => void }) {
  const [roi, setRoi] = useState<QuadRoi>({ x: 0.2, y: 0.2, w: 0.6, h: 0.6 });
  return <PlateRoiEditor printerId={1} value={roi} onChange={(r) => { setRoi(r); onChange(r); }} />;
}

// jsdom não tem PointerEvent: sem ele o fireEvent perde clientX/clientY.
if (!('PointerEvent' in window)) {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? 'mouse';
    }
  }
  (window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
}

describe('PlateRoiEditor', () => {
  function setup() {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const box = screen.getByTestId('plate-roi-editor').firstElementChild as HTMLDivElement;
    box.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    box.setPointerCapture = vi.fn();
    box.hasPointerCapture = vi.fn(() => true);
    box.releasePointerCapture = vi.fn();
    return { onChange, box };
  }

  it('arrasta um canto livre (toque) e o resto fica parado', () => {
    const { onChange, box } = setup();
    const corner = box.querySelector('[data-corner="0"]')!;
    fireEvent.pointerDown(corner, { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 20 });
    fireEvent.pointerMove(box, { pointerId: 1, pointerType: 'touch', clientX: 80, clientY: 30 });
    fireEvent.pointerUp(box, { pointerId: 1 });
    const last = onChange.mock.calls.at(-1)![0] as QuadRoi;
    expect(last.points![0]).toEqual([0.4, 0.3]);
    expect(last.points![1]).toEqual([0.8, 0.2]);
    expect(last.points![3]).toEqual([0.2, 0.8]);
  });

  it('arrasta a área inteira pelo meio (mouse)', () => {
    const { onChange, box } = setup();
    fireEvent.pointerDown(box, { pointerId: 2, clientX: 100, clientY: 50 });
    fireEvent.pointerMove(box, { pointerId: 2, clientX: 110, clientY: 55 });
    const last = onChange.mock.calls.at(-1)![0] as QuadRoi;
    expect(last.x).toBeCloseTo(0.25);
    expect(last.y).toBeCloseTo(0.25);
  });

  it('ignora toque fora da área (deixa rolar a tela)', () => {
    const { onChange, box } = setup();
    fireEvent.pointerDown(box, { pointerId: 3, clientX: 5, clientY: 5 });
    fireEvent.pointerMove(box, { pointerId: 3, clientX: 50, clientY: 50 });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('ajuste fino pelas setas no canto selecionado', () => {
    const { onChange, box } = setup();
    fireEvent.click(box.querySelector('[data-corner="2"]')!);
    fireEvent.click(screen.getAllByRole('button', { name: /selected corner|canto selecionado|nudge/i })[3]);
    const last = onChange.mock.calls.at(-1)![0] as QuadRoi;
    expect(last.points![2][0]).toBeCloseTo(0.805);
  });
});
