import { useEffect, useRef, useState, type PointerEvent } from 'react';
import platePhotoUrl from './textured-pei-a1.jpg';
import { renderPlatePhoto } from './platePhoto';
import type { Drawing, Machine, Paper, Pen, Placement, Rect, SimPoint } from './api';

export type Layer = 'vector' | 'original' | 'overlay' | 'simulation';
export type Edit = 'paper' | 'drawing' | 'exclude';
const SIZE = 760;
const PADDING = 48;
const round = (value: number) => Math.round(value * 10) / 10;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function stroke(ctx: CanvasRenderingContext2D, x: number, y: number, u: number, v: number, width: number) {
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(u, v);
  ctx.stroke();
}

function dot(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, 2 * Math.PI);
  ctx.fill();
}

function renderDrawing(ctx: CanvasRenderingContext2D, drawing: Drawing, position: Placement, layer: Layer, image: HTMLImageElement | null, excluded: Set<number>, editing: boolean) {
  const scale = position.width / drawing.width;
  ctx.save();
  ctx.translate(position.cx, -position.cy);
  ctx.rotate(-position.rotation * Math.PI / 180);
  ctx.scale(scale, scale);
  ctx.translate(-drawing.width / 2, -drawing.height / 2);
  if (image && layer !== 'vector') ctx.drawImage(image, 0, 0, drawing.width, drawing.height);
  if (layer !== 'original') {
    ctx.lineCap = 'round';
    for (const [index, { p, c }] of drawing.strokes.entries()) {
      if (excluded.has(index) && !editing) continue;
      ctx.fillStyle = ctx.strokeStyle = excluded.has(index) ? '#ba5553' : layer === 'overlay' ? '#237c78' : '#182427';
      if (p.length === 3) dot(ctx, p[0], p[1], p[2] / 2);
      for (let i = 3; i < p.length; i += 3) {
        stroke(ctx, p[i - 3], p[i - 2], p[i], p[i + 1], (p[i - 1] + p[i + 2]) / 2);
      }
      if (c && p.length > 3) {
        stroke(ctx, p.at(-3)!, p.at(-2)!, p[0], p[1], (p.at(-1)! + p[2]) / 2);
      }
    }
  }
  ctx.strokeStyle = '#278e91';
  ctx.lineWidth = 0.5 / scale;
  ctx.strokeRect(0, 0, drawing.width, drawing.height);
  ctx.restore();
}

function renderSimulation(ctx: CanvasRenderingContext2D, points: SimPoint[], time: number, pen: Pen, travel: boolean) {
  let cursor: SimPoint | undefined;
  ctx.lineCap = 'round';
  for (const point of points) {
    if (point[3] > time) break;
    const [x, y, depth] = point;
    const down = depth >= 0 && cursor && cursor[2] >= 0;
    if (cursor && (down || travel)) {
      const pressure = clamp(depth / Math.max(0.01, pen.depth_max), 0, 1);
      ctx.strokeStyle = down ? `hsl(${178 - pressure * 140} 65% 34%)` : '#768da0';
      ctx.setLineDash(down ? [] : [1, 1]);
      stroke(ctx, cursor[0], -cursor[1], x, -y, down ? 0.45 + 0.55 * pressure : 0.35);
      if (down && cursor[0] === x && cursor[1] === y) {
        ctx.fillStyle = ctx.strokeStyle;
        dot(ctx, x, -y, 0.45);
      }
    }
    cursor = point;
  }
  ctx.setLineDash([]);
  if (cursor) {
    ctx.fillStyle = '#08858c';
    dot(ctx, cursor[0], -cursor[1], 1.5);
  }
}

function imagePoint(drawing: Drawing, placement: Placement, x: number, y: number) {
  const angle = placement.rotation * Math.PI / 180;
  const dx = x - placement.cx;
  const dy = y - placement.cy;
  const imageScale = placement.width / drawing.width;
  const u = (dx * Math.cos(angle) + dy * Math.sin(angle)) / imageScale + drawing.width / 2;
  const v = (dx * Math.sin(angle) - dy * Math.cos(angle)) / imageScale + drawing.height / 2;
  return { u, v, imageScale };
}

function hitStroke(drawing: Drawing, placement: Placement, x: number, y: number, toleranceMm: number) {
  const { u, v, imageScale } = imagePoint(drawing, placement, x, y);
  let nearest = toleranceMm / imageScale;
  let hit = -1;
  for (const [index, { p, c }] of drawing.strokes.entries()) {
    const count = p.length / 3;
    for (let i = 0; i < count; i++) {
      const a = i * 3;
      const b = i + 1 < count ? a + 3 : c ? 0 : a;
      const sx = p[b] - p[a];
      const sy = p[b + 1] - p[a + 1];
      const lengthSquared = sx * sx + sy * sy;
      const t = lengthSquared ? clamp(((u - p[a]) * sx + (v - p[a + 1]) * sy) / lengthSquared, 0, 1) : 0;
      const distance = Math.hypot(u - p[a] - sx * t, v - p[a + 1] - sy * t) - (p[a + 2] + p[b + 2]) / 4;
      if (distance < nearest) {
        nearest = distance;
        hit = index;
      }
    }
  }
  return hit;
}

type Point = { x: number; y: number };
type Drag = {
  id: number; isTouch: boolean; origin: Point; current: Point; size: number;
  view: number[]; paper: Paper; placement: Placement;
};
type Pinch = { id: number; second: Point; distance: number; placement: Placement };

function pointerPoint(event: PointerEvent<HTMLCanvasElement>): Point {
  return { x: event.clientX, y: event.clientY };
}

function resizedWidth(width: number, ratio: number) {
  return round(clamp(width * ratio, 1, 1000));
}

type Props = {
  machine: Machine; paper: Paper; area: Rect | null; pen: Pen;
  drawing: Drawing | null; placement: Placement; imageUrl?: string; layer: Layer; edit: Edit;
  points?: SimPoint[]; time: number; travel: boolean; locked: boolean; excluded: Set<number>;
  onPaper: (paper: Paper) => void; onPlacement: (placement: Placement) => void; onToggleStroke: (index: number) => void;
};

export function Plate({ machine, paper, area, pen, drawing, placement, imageUrl, layer, edit, points, time, travel, locked, excluded, onPaper, onPlacement, onToggleStroke }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [platePhoto, setPlatePhoto] = useState<HTMLImageElement | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<Drag | null>(null);
  const pinch = useRef<Pinch | null>(null);
  const w = machine.plate_w;
  const h = machine.plate_h;
  const view = drag.current?.view ?? [
    Math.min(0, paper.x), Math.max(h, paper.y + paper.h),
    Math.max(w, paper.x + paper.w) - Math.min(0, paper.x),
    Math.max(h, paper.y + paper.h) - Math.min(0, paper.y),
  ];
  const [left, top, spanX, spanY] = view;
  const scale = (SIZE - 2 * PADDING) / Math.max(spanX, spanY);
  const ox = (SIZE - spanX * scale) / 2 - left * scale;
  const oy = (SIZE - spanY * scale) / 2 + top * scale;

  useEffect(() => {
    const photo = new Image();
    photo.onload = () => setPlatePhoto(photo);
    photo.src = platePhotoUrl;
    return () => { photo.onload = null; };
  }, []);

  useEffect(() => {
    if (!imageUrl) return;
    const next = new Image();
    next.onload = () => setImage(next);
    next.src = imageUrl;
    return () => { next.onload = null; };
  }, [imageUrl]);

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, SIZE, SIZE);
    ctx.setTransform(scale, 0, 0, scale, ox, oy);
    if (platePhoto) renderPlatePhoto(ctx, platePhoto, w, h);
    else {
      ctx.fillStyle = '#c7a36a';
      ctx.fillRect(0, -h, w, h);
    }
    ctx.lineWidth = 0.55;
    ctx.fillStyle = '#f5f1e7';
    ctx.fillRect(paper.x, -paper.y - paper.h, paper.w, paper.h);
    ctx.strokeStyle = edit === 'paper' ? '#e7a34d' : '#a39378';
    ctx.strokeRect(paper.x, -paper.y - paper.h, paper.w, paper.h);
    if (area) {
      ctx.strokeStyle = '#158986';
      ctx.setLineDash([2, 1.2]);
      ctx.strokeRect(area[0], -area[3], area[2] - area[0], area[3] - area[1]);
      ctx.setLineDash([]);
    }
    if (layer === 'simulation' && points) renderSimulation(ctx, points, time, pen, travel);
    else if (drawing) renderDrawing(ctx, drawing, placement, layer, image?.src === imageUrl ? image : null, excluded, edit === 'exclude');
    ctx.fillStyle = '#31bdb0';
    dot(ctx, 0, 0, 1.6);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.font = '22px system-ui';
    ctx.fillStyle = '#9daeb9';
    ctx.fillText('0,0', ox - 8, oy + 43);
    ctx.textAlign = 'right';
    ctx.fillText('Frente da A1', ox + w * scale, oy + 43);
    ctx.textAlign = 'start';
  }, [area, drawing, edit, excluded, h, image, imageUrl, layer, ox, oy, paper, pen, placement, platePhoto, points, scale, time, travel, w]);

  useEffect(() => {
    const element = canvas.current;
    if (!element || !drawing || locked || edit !== 'drawing') return;
    let width = placement.width;
    function resizeWithWheel(event: WheelEvent) {
      if (!element || !drawing || drag.current || !event.cancelable || !event.deltaY) return;
      const box = element.getBoundingClientRect();
      const x = ((event.clientX - box.left) * SIZE / box.width - ox) / scale;
      const y = (oy - (event.clientY - box.top) * SIZE / box.width) / scale;
      const { u, v } = imagePoint(drawing, { ...placement, width }, x, y);
      if (u < 0 || u > drawing.width || v < 0 || v > drawing.height) return;
      event.preventDefault();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? box.height : 1);
      const nextWidth = resizedWidth(width, Math.exp(-clamp(pixels, -180, 180) / 500));
      if (nextWidth === width) return;
      width = nextWidth;
      onPlacement({ ...placement, width });
    }
    element.addEventListener('wheel', resizeWithWheel, { passive: false });
    return () => element.removeEventListener('wheel', resizeWithWheel);
  }, [drawing, edit, locked, onPlacement, ox, oy, placement, scale]);

  function begin(event: PointerEvent<HTMLCanvasElement>) {
    if (locked || event.button !== 0 || (edit !== 'paper' && !drawing)) return;
    const currentDrag = drag.current;
    const point = pointerPoint(event);
    if (currentDrag) {
      if (edit !== 'drawing' || !currentDrag.isTouch || event.pointerType !== 'touch' || pinch.current) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      pinch.current = {
        id: event.pointerId,
        second: point,
        distance: Math.max(1, Math.hypot(point.x - currentDrag.current.x, point.y - currentDrag.current.y)),
        placement,
      };
      return;
    }

    const box = event.currentTarget.getBoundingClientRect();
    const x = ((point.x - box.left) * SIZE / box.width - ox) / scale;
    const y = (oy - (point.y - box.top) * SIZE / box.width) / scale;
    if (edit === 'exclude' && drawing) {
      const hit = hitStroke(drawing, placement, x, y, 8 * SIZE / (scale * box.width));
      if (hit !== -1) onToggleStroke(hit);
      return;
    }
    if (edit === 'paper' && (x < paper.x || x > paper.x + paper.w || y < paper.y || y > paper.y + paper.h)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      id: event.pointerId, isTouch: event.pointerType === 'touch', origin: point, current: point,
      size: box.width * scale / SIZE, paper, placement, view,
    };
    setDragging(true);
  }

  function move(event: PointerEvent<HTMLCanvasElement>) {
    const start = drag.current;
    if (locked || !start) return;
    const zoom = pinch.current;
    if (start.id === event.pointerId) start.current = pointerPoint(event);
    else if (zoom?.id === event.pointerId) zoom.second = pointerPoint(event);
    else return;

    if (zoom) {
      const distance = Math.hypot(zoom.second.x - start.current.x, zoom.second.y - start.current.y);
      const width = resizedWidth(zoom.placement.width, distance / zoom.distance);
      if (width !== placement.width) onPlacement({ ...zoom.placement, width });
      return;
    }
    const dx = (start.current.x - start.origin.x) / start.size;
    const dy = (start.origin.y - start.current.y) / start.size;
    if (edit === 'paper') onPaper({ ...start.paper, x: round(clamp(start.paper.x + dx, -400, 400)), y: round(clamp(start.paper.y + dy, -400, 400)) });
    else onPlacement({ ...start.placement, cx: round(clamp(start.placement.cx + dx, -500, 800)), cy: round(clamp(start.placement.cy + dy, -500, 800)) });
  }

  function end(event: PointerEvent<HTMLCanvasElement>) {
    if (drag.current?.id !== event.pointerId && pinch.current?.id !== event.pointerId) return;
    drag.current = null;
    pinch.current = null;
    setDragging(false);
  }

  return <canvas
    ref={canvas} className="plotter-plate" width={SIZE} height={SIZE} aria-label="Vista superior da mesa da Bambu Lab A1"
    style={{ touchAction: locked ? 'auto' : 'none', cursor: locked ? 'default' : edit === 'exclude' ? 'crosshair' : dragging ? 'grabbing' : 'grab' }}
    onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
  />;
}
