/**
 * Barras de temperatura do bico e da mesa no card da impressora (custom(temp-bars)).
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../__tests__/mocks/server';
import { render } from '../../__tests__/utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { setTempBarsOverride, setSinglePrinterModeOverride } from '../flags';
import {
  TEMP_BAR_COLD,
  TEMP_BAR_HOT,
  tempBarColor,
  tempBarOpacity,
  tempFraction,
} from '../printer/tempBarScale';
import { printerA1, idleStatus, installMemoryStorage } from './fixtures';

describe('escala, clamp, opacidade e cor', () => {
  it('mesa 27→67 e bico 25→250 viram 0→1, com clamp', () => {
    expect(tempFraction('bed', 27)).toBe(0);
    expect(tempFraction('bed', 20)).toBe(0);
    expect(tempFraction('bed', 67)).toBe(1);
    expect(tempFraction('bed', 47)).toBeCloseTo(0.5);
    expect(tempFraction('nozzle', 25)).toBe(0);
    expect(tempFraction('nozzle', 250)).toBe(1);
    expect(tempFraction('nozzle', 137.5)).toBeCloseTo(0.5);
    expect(tempFraction('bed', 5)).toBe(0);
    expect(tempFraction('bed', 110)).toBe(1);
    expect(tempFraction('nozzle', -3)).toBe(0);
    expect(tempFraction('nozzle', 300)).toBe(1);
    expect(tempFraction('nozzle', undefined)).toBe(0);
    expect(tempFraction('bed', NaN)).toBe(0);
  });

  it('opacidade 0,6 abaixo de 30 °C (mesa) / 40 °C (bico), 1 a partir do limiar', () => {
    expect(tempBarOpacity('bed', 29.9)).toBe(0.6);
    expect(tempBarOpacity('bed', 30)).toBe(1);
    expect(tempBarOpacity('nozzle', 39.9)).toBe(0.6);
    expect(tempBarOpacity('nozzle', 40)).toBe(1);
    // cada barra decide pela própria escala: 35 °C é "frio" no bico e "quente" na mesa
    expect(tempBarOpacity('bed', 35)).toBe(1);
    expect(tempBarOpacity('nozzle', 35)).toBe(0.6);
  });

  it('cor vai de azul claro (0) a vermelho vivo (1), com clamp', () => {
    expect(tempBarColor(0)).toBe(TEMP_BAR_COLD);
    expect(tempBarColor(1)).toBe(TEMP_BAR_HOT);
    expect(tempBarColor(-1)).toBe(TEMP_BAR_COLD);
    expect(tempBarColor(2)).toBe(TEMP_BAR_HOT);
    // meio da escala: violeta vivo (HSL), não o lilás acinzentado do RGB linear
    expect(tempBarColor(0.5)).toBe('#ce4bff');
    expect(tempBarColor(0.25)).toBe('#7163ff');
    expect(tempBarColor(0.75)).toBe('#ff33b5');
  });
});

function setup(temperatures: Record<string, number>) {
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json([printerA1])),
    http.get('/api/v1/printers/:id/status', () => HttpResponse.json({ ...idleStatus, temperatures })),
    http.get('/api/v1/queue/', () => HttpResponse.json([])),
  );
  render(<PrintersPage />);
}

describe('no card da impressora', () => {
  beforeEach(() => {
    installMemoryStorage();
    setSinglePrinterModeOverride('on');
  });
  afterEach(() => {
    setSinglePrinterModeOverride(null);
    setTempBarsOverride(null);
  });

  it('flag ligada: barra do bico e da mesa, número mantido, largura/cor/opacidade/alvo', async () => {
    setTempBarsOverride('on');
    setup({ nozzle: 137.5, nozzle_target: 220, bed: 29, bed_target: 0, chamber: 28 });
    const nozzleFill = await screen.findByTestId('temp-bar-nozzle-fill');
    const bedFill = screen.getByTestId('temp-bar-bed-fill');
    expect(nozzleFill.style.width).toBe('50%');
    expect(nozzleFill.style.opacity).toBe('1');
    expect(nozzleFill.style.backgroundColor).toBe('rgb(206, 75, 255)');
    expect(bedFill.style.width).toBe('5%');
    expect(bedFill.style.opacity).toBe('0.6');
    // números do upstream continuam
    expect(screen.getByText('138°C')).toBeTruthy();
    expect(screen.getByText('29°C')).toBeTruthy();
    // alvo: tracinho no bico (220), nenhum na mesa (alvo 0)
    expect(screen.getByTestId('temp-bar-nozzle-target').style.left).toBe('86.7%');
    expect(screen.queryByTestId('temp-bar-bed-target')).toBeNull();
    // a barra fica dentro do cartão da temperatura, logo após o número
    expect(screen.getByTestId('temp-bar-bed').previousElementSibling?.textContent).toBe('29°C');
    // os dois blocos viram linhas horizontais (layout em tempBars.css)
    expect(screen.getByTestId('temp-bar-bed').parentElement?.getAttribute('data-temp-row')).toBe('bed');
    expect(screen.getByTestId('temp-bar-nozzle').parentElement?.getAttribute('data-temp-row')).toBe('nozzle');
    // horas totais de impressão saíram do card
    expect(screen.queryByText('Impressão')).toBeNull();
  });

  it('flag desligada: nenhuma barra (DOM do upstream)', async () => {
    setTempBarsOverride('off');
    setup({ nozzle: 200, bed: 60, chamber: 25 });
    await waitFor(() => expect(screen.getByText('200°C')).toBeTruthy());
    expect(document.querySelector('[data-testid^="temp-bar"]')).toBeNull();
    expect(document.querySelector('[data-temp-row]')).toBeNull();
  });

  it('bico duplo (L / R) não ganha barra no bico, só na mesa', async () => {
    setTempBarsOverride('on');
    setup({ nozzle: 200, nozzle_2: 190, bed: 60, chamber: 25 });
    await screen.findByTestId('temp-bar-bed');
    expect(screen.queryByTestId('temp-bar-nozzle')).toBeNull();
    expect(document.querySelector('[data-temp-row]')).toBeNull();
  });
});
