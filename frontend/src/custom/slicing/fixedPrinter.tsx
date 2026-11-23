import { useId, useState } from 'react';
import { LockKeyhole } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { PresetRef, SlicerPipeline, UnifiedPresetsResponse } from '../../api/client';
import { findPreset, listedRef } from '../../utils/slicePresetPicker';
import { presetCompatibility, type PrinterCompatibilityIndex } from '../../utils/slicerPrinterMatch';

export type FixedPrinterPresets = Record<string, PresetRef>;

export function useA1Nozzle(options: FixedPrinterPresets | null | undefined) {
  const [selection, select] = useState<string>();
  const preset = selection ? options?.[selection] : undefined;
  return { preset, diameter: preset ? selection : undefined, select };
}

export function pipelineFitsFixedPrinter(
  pipeline: SlicerPipeline,
  presets: UnifiedPresetsResponse | undefined,
  compatibility: PrinterCompatibilityIndex,
  printer: PresetRef | undefined,
): boolean {
  if (!presets?.fixed_printer_presets) return true;
  if (!printer) return false;
  const fits = (ref: PresetRef, slot: 'process' | 'filament') => {
    const preset = findPreset(presets, listedRef(presets, ref), slot);
    return preset != null && presetCompatibility(preset, slot, printer.id, compatibility) !== 'mismatch';
  };
  return fits(pipeline.process_preset, 'process') && pipeline.filament_presets.every(ref => fits(ref, 'filament'));
}

export function FixedSlicePrinter({ options, value, onChange, disabled }: {
  options: FixedPrinterPresets;
  value: string | undefined;
  onChange: (diameter: string) => void;
  disabled?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const groupName = useId();

  return (
    <div className="space-y-2 rounded-md border border-bambu-dark-tertiary px-3 py-2.5 text-sm">
      <div className="flex items-center gap-2">
        <LockKeyhole className="h-4 w-4 shrink-0 text-bambu-gray" aria-hidden />
        <span className="text-bambu-gray">{t('slice.printer')}</span>
        <span className="font-medium text-white">Bambu Lab A1</span>
      </div>
      <fieldset disabled={disabled}>
        <legend className="mb-1.5 font-medium text-white">{t('customFixedSlicePrinter.chooseNozzle')}</legend>
        <div className="grid grid-cols-2 gap-2">
          {Object.keys(options).map((diameter) => (
            <label key={diameter}>
              <input
                type="radio"
                className="peer sr-only"
                name={groupName}
                value={diameter}
                checked={value === diameter}
                onChange={() => onChange(diameter)}
                required
              />
              <span className="flex min-h-[44px] cursor-pointer items-center justify-center rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 font-medium text-white peer-checked:border-bambu-green peer-checked:bg-bambu-green peer-checked:text-bambu-dark peer-focus-visible:ring-2 peer-focus-visible:ring-bambu-green peer-disabled:cursor-default">
                {Number(diameter).toLocaleString(i18n.language)} mm
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );
}
