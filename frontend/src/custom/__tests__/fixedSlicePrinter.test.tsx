import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { api, type PipelineRun, type PresetRef, type SlicerPipeline, type UnifiedPresetsResponse } from '../../api/client';
import { render } from '../../__tests__/utils';
import { RunWithPipelineModal } from '../../components/RunWithPipelineModal';
import { SliceModal } from '../../components/SliceModal';
import { SliceJobTrackerProvider } from '../../contexts/SliceJobTrackerContext';
import '../i18n';

const a1_02 = 'Bambu Lab A1 0.2 nozzle';
const a1_04 = 'Bambu Lab A1 0.4 nozzle';
const x1c = 'Bambu Lab X1 Carbon 0.4 nozzle';
const standard = (id: string): PresetRef => ({ source: 'standard', id });
const process02 = '0.10mm Standard @BBL A1 0.2 nozzle';
const process04 = '0.20mm Standard @BBL A1';
const pla02 = 'Generic PLA @BBL A1 0.2 nozzle';
const pla04 = 'Generic PLA @BBL A1';
const empty = { printer: [], process: [], filament: [] };
const options = { '0.2': standard(a1_02), '0.4': standard(a1_04) };

const presets: UnifiedPresetsResponse = {
  local: empty,
  orca_cloud: empty,
  cloud: empty,
  standard: {
    // An official profile can be hidden behind its cloud twin in the listing.
    printer: [{ ...standard(x1c), name: x1c }],
    process: [
      { ...standard(process02), name: process02, compatible_printers: [a1_02] },
      { ...standard(process04), name: process04, compatible_printers: [a1_04] },
    ],
    filament: [
      { ...standard(pla02), name: pla02, filament_type: 'PLA', compatible_printers: [a1_02] },
      { ...standard(pla04), name: pla04, filament_type: 'PLA', compatible_printers: [a1_04] },
    ],
  },
  cloud_status: 'ok',
  orca_cloud_status: 'ok',
  fixed_printer_presets: options,
};

const pipeline: SlicerPipeline = {
  id: 5, name: 'Saved pipeline', description: null, printer_preset: standard(x1c),
  process_preset: standard(process04), filament_presets: [standard(pla04)], bed_type: null,
  target_kind: 'specific_printer', target_printer_id: 1, target_model_class: null,
  fanout_strategy: 'max_parallel', created_by: null, created_at: '', updated_at: '',
};

afterEach(() => vi.restoreAllMocks());

it.each([
  [x1c, '0.2', a1_02, process02, pla02],
  [a1_04, '0.4', a1_04, process04, pla04],
])('requires a nozzle choice for a project saved for %s', async (sourcePrinter, diameter, printer, process, pla) => {
  vi.spyOn(api, 'getSlicerPresets').mockResolvedValue(presets);
  vi.spyOn(api, 'getSlicerPrinterModels').mockResolvedValue({ 'Bambu Lab A1': 'A1' });
  vi.spyOn(api, 'getSlicerLoadedSpools').mockResolvedValue({ printers: [] });
  vi.spyOn(api, 'getSlicerPresetValues').mockResolvedValue({ values: {}, reason: 'ok', resolved: true });
  vi.spyOn(api, 'getLibraryFilePlates').mockResolvedValue({
    file_id: 98, filename: 'Figurine.3mf', is_multi_plate: false, plates: [],
    embedded_printer: sourcePrinter, embedded_process: process04,
  });
  vi.spyOn(api, 'getLibraryFileFilamentRequirements').mockResolvedValue({
    file_id: 98, filename: 'Figurine.3mf', filaments: [],
  });
  vi.spyOn(api, 'listSlicerPipelines').mockResolvedValue({ pipelines: [pipeline] });
  const slice = vi.spyOn(api, 'sliceLibraryFile').mockRejectedValue(new Error('Test stops after submit'));

  const modal = () => (
    <SliceJobTrackerProvider>
      <SliceModal source={{ kind: 'libraryFile', id: 98, filename: 'Figurine.3mf' }} onClose={() => {}} />
    </SliceJobTrackerProvider>
  );
  const { rerender } = render(modal());
  await screen.findByText('Bambu Lab A1');
  expect(screen.queryByRole('combobox', { name: 'Printer profile' })).toBeNull();
  expect(screen.queryByLabelText(/Only printers that are online/)).toBeNull();

  const nozzle02 = screen.getByRole('radio', { name: '0.2 mm' });
  const nozzle04 = screen.getByRole('radio', { name: '0.4 mm' });
  expect(nozzle02).not.toBeChecked();
  expect(nozzle04).not.toBeChecked();
  const submit = screen.getByRole('button', { name: 'Slice' });
  expect(submit).toBeDisabled();
  fireEvent.click(submit);
  expect(slice).not.toHaveBeenCalled();

  fireEvent.click(nozzle04);
  await screen.findByRole('option', { name: 'Saved pipeline' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Apply pipeline' }), { target: { value: '5' } });
  if (diameter === '0.2') {
    fireEvent.click(nozzle02);
    expect(screen.queryByRole('option', { name: 'Saved pipeline' })).toBeNull();
  }
  if (sourcePrinter === x1c) expect(screen.queryByLabelText(/built-in settings/i)).toBeNull();
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  await waitFor(() => expect(slice).toHaveBeenCalledWith(98, expect.objectContaining({
    a1_nozzle_diameter: diameter,
    printer_preset: standard(printer),
    process_preset: standard(process),
    filament_presets: [standard(pla)],
  })));

  rerender(<></>);
  rerender(modal());
  expect(await screen.findByRole('radio', { name: '0.2 mm' })).not.toBeChecked();
  expect(screen.getByRole('radio', { name: '0.4 mm' })).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Slice' })).toBeDisabled();
});

it('requires a nozzle before a saved pipeline can run', async () => {
  vi.spyOn(api, 'listSlicerPipelines').mockResolvedValue({ pipelines: [pipeline], fixed_printer_presets: options });
  vi.spyOn(api, 'getPrinters').mockResolvedValue([]);
  const check = vi.spyOn(api, 'checkPipelineEligibility').mockResolvedValue({
    ok: true, target_kind: 'specific_printer', target_model_class: null, target_printer_id: 1,
    target_printer_name: 'A1', issues: [], printer_reports: [],
  });
  const run = vi.spyOn(api, 'runPipeline').mockResolvedValue({ slice_job_id: null } as PipelineRun);

  render(
    <SliceJobTrackerProvider>
      <RunWithPipelineModal source={{ kind: 'archive', id: 98, filename: 'Figurine.3mf' }} onClose={() => {}} />
    </SliceJobTrackerProvider>,
  );
  const pick = await screen.findByRole('button', { name: /Saved pipeline/ });
  expect(pick).toBeDisabled();
  fireEvent.click(pick);
  expect(check).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('radio', { name: '0.2 mm' }));
  expect(pick).toBeEnabled();
  fireEvent.click(pick);
  await waitFor(() => expect(run).toHaveBeenCalledWith(5, { kind: 'archive', id: 98 }, false, 1, '0.2'));
});
