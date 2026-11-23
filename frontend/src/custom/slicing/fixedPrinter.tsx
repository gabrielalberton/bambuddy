import { LockKeyhole } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { PresetRef, SlicerPipeline, UnifiedPresetsResponse } from '../../api/client';
import { findPreset, listedRef } from '../../utils/slicePresetPicker';
import { presetCompatibility, type PrinterCompatibilityIndex } from '../../utils/slicerPrinterMatch';

export function pipelineFitsFixedPrinter(
  pipeline: SlicerPipeline,
  presets: UnifiedPresetsResponse | undefined,
  compatibility: PrinterCompatibilityIndex,
): boolean {
  const printer = presets?.fixed_printer_preset;
  if (!presets || !printer) return true;
  const fits = (ref: PresetRef, slot: 'process' | 'filament') => {
    const preset = findPreset(presets, listedRef(presets, ref), slot);
    return preset != null && presetCompatibility(preset, slot, printer.id, compatibility) !== 'mismatch';
  };
  return fits(pipeline.process_preset, 'process') && pipeline.filament_presets.every(ref => fits(ref, 'filament'));
}

export function FixedSlicePrinter({ preset }: { preset: PresetRef }) {
  const { t, i18n } = useTranslation();
  const diameter = Number(preset.id.match(/ ([\d.]+) nozzle$/)?.[1]);
  const name = Number.isFinite(diameter)
    ? t('customFixedSlicePrinter.profile', { diameter: diameter.toLocaleString(i18n.language) })
    : preset.id;
  return (
    <div className="flex items-center gap-2 rounded-md border border-bambu-dark-tertiary px-3 py-2 text-sm">
      <LockKeyhole className="h-4 w-4 shrink-0 text-bambu-gray" aria-hidden />
      <span className="text-bambu-gray">{t('slice.printer')}</span>
      <span className="font-medium text-white">{name}</span>
    </div>
  );
}
