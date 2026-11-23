import { useEffect } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { BufferGeometry, Group, Mesh, MeshStandardMaterial } from 'three';
import { describe, expect, it } from 'vitest';
import '../i18n';
import { useModelAppearance } from '../modelPreview/appearance';

function Preview({ group }: { group: Group }) {
  const { attachAppearance, appearanceControls } = useModelAppearance();
  useEffect(() => attachAppearance(group), [attachAppearance, group]);
  return appearanceControls;
}

function model(sourceColors: number[]) {
  const group = new Group();
  const materials = sourceColors.map(color => new MeshStandardMaterial({ color }));
  for (const material of materials) group.add(new Mesh(new BufferGeometry(), material));
  return { group, colors: () => materials.map(material => material.color.getHex()) };
}

const coloredButton = () => screen.getByRole('button', { name: 'Color' });
const whiteButton = () => screen.getByRole('button', { name: 'White' });

describe('model appearance', () => {
  it('opens white pieces in different display colors and can switch back from white', () => {
    const { group, colors } = model(Array(6).fill(0xffffff));
    render(<Preview group={group} />);

    expect(coloredButton().getAttribute('aria-pressed')).toBe('true');
    const previewColors = colors();
    expect(new Set(previewColors).size).toBe(6);
    expect(previewColors).not.toContain(0xffffff);
    expect(screen.queryByText('Preview colors')).not.toBeNull();

    fireEvent.click(whiteButton());
    expect(whiteButton().getAttribute('aria-pressed')).toBe('true');
    expect(colors()).toEqual(Array(6).fill(0xffffff));
    expect(screen.queryByText('Preview colors')).toBeNull();

    fireEvent.click(coloredButton());
    expect(colors()).toEqual(previewColors);
  });

  it('restores the file colors, including white, after temporary monochrome display', () => {
    const original = [0x563a25, 0x1f130c, 0xffffff, 0xd69a75];
    const { group, colors } = model(original);
    render(<Preview group={group} />);
    expect(colors()).toEqual(original);
    expect(screen.queryByText('Preview colors')).toBeNull();

    fireEvent.click(whiteButton());
    expect(colors()).toEqual(Array(4).fill(0xffffff));
    fireEvent.click(coloredButton());
    expect(colors()).toEqual(original);
  });
});
