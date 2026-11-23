import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Color, Mesh, MeshStandardMaterial, type Group } from 'three';
import { modelPreviewEnabled } from './preview';

type Appearance = 'colored' | 'white';

const WHITE = 0xffffff;
const PART_COLORS = [0x78a9df, 0xd09369, 0x72b89b, 0xaf96d2, 0xcf7a88, 0xd2b164, 0x72adc4, 0xa6bb6e];

interface MaterialColor {
  material: MeshStandardMaterial;
  color: Color;
}

function paint(materials: MaterialColor[], appearance: Appearance) {
  for (const { material, color } of materials) {
    if (appearance === 'white') material.color.setHex(WHITE);
    else material.color.copy(color);
  }
}

export function useModelAppearance() {
  const { t } = useTranslation();
  const enabled = modelPreviewEnabled();
  const [appearance, setAppearance] = useState<Appearance>('colored');
  const [usesPartColors, setUsesPartColors] = useState(false);
  const currentAppearance = useRef(appearance);
  const materialColors = useRef<MaterialColor[]>([]);

  const attachAppearance = useCallback((group: Group) => {
    if (!enabled) return;
    const materials = new Set<MeshStandardMaterial>();
    group.traverse(object => {
      if (!(object instanceof Mesh)) return;
      const candidates = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of candidates) {
        if (material instanceof MeshStandardMaterial) materials.add(material);
      }
    });
    const baseMaterials = [...materials];
    const allWhite = baseMaterials.length > 0 && baseMaterials.every(material => material.color.getHex() === WHITE);
    materialColors.current = baseMaterials.map((material, index) => ({
      material,
      color: allWhite ? new Color(PART_COLORS[index % PART_COLORS.length]) : material.color.clone(),
    }));
    paint(materialColors.current, currentAppearance.current);
    setUsesPartColors(allWhite);
  }, [enabled]);

  const select = (mode: Appearance) => {
    currentAppearance.current = mode;
    paint(materialColors.current, mode);
    setAppearance(mode);
  };

  const appearanceControls = enabled && (
    <div className="pointer-events-none absolute left-3 top-3 flex flex-col items-start gap-1">
      <div role="group" aria-label={t('customModelAppearance.label')}
        className="pointer-events-auto inline-flex rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary p-0.5">
        {(['colored', 'white'] as const).map(mode => (
          <button key={mode} type="button" aria-pressed={appearance === mode} onClick={() => select(mode)}
            className={`min-h-[44px] rounded-md px-3 text-sm focus-visible:ring-2 focus-visible:ring-bambu-green ${
              appearance === mode ? 'bg-bambu-dark-tertiary font-semibold text-white' : 'text-bambu-gray-light hover:text-white'
            }`}>
            {t(`customModelAppearance.${mode}`)}
          </button>
        ))}
      </div>
      {appearance === 'colored' && usesPartColors && (
        <span className="rounded bg-bambu-dark-secondary px-1.5 py-0.5 text-xs text-bambu-gray-light">
          {t('customModelAppearance.previewColors')}
        </span>
      )}
    </div>
  );
  return { attachAppearance, appearanceControls };
}
