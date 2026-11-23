import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { api, type PresetRef, type UnifiedPresetsResponse } from '../../api/client';
import { render } from '../../__tests__/utils';
import { SliceModal } from '../../components/SliceModal';
import { SliceJobTrackerProvider } from '../../contexts/SliceJobTrackerContext';
import '../i18n';

const a1 = 'Bambu Lab A1 0.4 nozzle';
const x1c = 'Bambu Lab X1 Carbon 0.4 nozzle';
const standard = (id: string): PresetRef => ({ source: 'standard', id });
const process = '0.20mm Standard @BBL A1';
const pla = 'Generic PLA @BBL A1';
const empty = { printer: [], process: [], filament: [] };

const presets: UnifiedPresetsResponse = {
  local: empty,
  orca_cloud: empty,
  cloud: empty,
  standard: {
    // The server can lock to a bundled preset even when the listing has
    // hidden its row in favour of a Bambu Cloud twin.
    printer: [{ ...standard(x1c), name: x1c }],
    process: [{ ...standard(process), name: process, compatible_printers: [a1] }],
    filament: [{ ...standard(pla), name: pla, filament_type: 'PLA', compatible_printers: [a1] }],
  },
  cloud_status: 'ok',
  orca_cloud_status: 'ok',
  fixed_printer_preset: standard(a1),
};

afterEach(() => vi.restoreAllMocks());

it.each([x1c, a1])('shows A1 as read-only and submits it for a project saved for %s', async (sourcePrinter) => {
  vi.spyOn(api, 'getSlicerPresets').mockResolvedValue(presets);
  vi.spyOn(api, 'getSlicerPrinterModels').mockResolvedValue({ 'Bambu Lab A1': 'A1' });
  vi.spyOn(api, 'getSlicerLoadedSpools').mockResolvedValue({ printers: [] });
  vi.spyOn(api, 'getLibraryFilePlates').mockResolvedValue({
    file_id: 98, filename: 'Figurine.3mf', is_multi_plate: false, plates: [],
    embedded_printer: sourcePrinter, embedded_process: process,
  });
  vi.spyOn(api, 'getLibraryFileFilamentRequirements').mockResolvedValue({
    file_id: 98, filename: 'Figurine.3mf', filaments: [],
  });
  vi.spyOn(api, 'listSlicerPipelines').mockResolvedValue({
    pipelines: [{
      id: 5, name: 'Saved pipeline', description: null, printer_preset: standard(x1c),
      process_preset: standard(process), filament_presets: [standard(pla)], bed_type: null,
      target_kind: 'specific_printer', target_printer_id: null, target_model_class: null,
      fanout_strategy: 'max_parallel', created_by: null, created_at: '', updated_at: '',
    }],
  });
  const slice = vi.spyOn(api, 'sliceLibraryFile').mockRejectedValue(new Error('Test stops after submit'));

  render(
    <SliceJobTrackerProvider>
      <SliceModal source={{ kind: 'libraryFile', id: 98, filename: 'Figurine.3mf' }} onClose={() => {}} />
    </SliceJobTrackerProvider>,
  );
  await screen.findByText('Bambu Lab A1 · 0.4 mm nozzle');
  expect(screen.queryByRole('combobox', { name: 'Printer profile' })).toBeNull();
  expect(screen.queryByLabelText(/Only printers that are online/)).toBeNull();
  if (sourcePrinter === x1c) expect(screen.queryByLabelText(/built-in settings/i)).toBeNull();
  await screen.findByRole('option', { name: 'Saved pipeline' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Apply pipeline' }), { target: { value: '5' } });
  const submit = await screen.findByRole<HTMLButtonElement>('button', { name: 'Slice' });
  await waitFor(() => expect(submit.disabled).toBe(false));
  fireEvent.click(submit);
  await waitFor(() => expect(slice).toHaveBeenCalledWith(98, expect.objectContaining({
    printer_preset: standard(a1), process_preset: standard(process), filament_presets: [standard(pla)],
  })));
});
