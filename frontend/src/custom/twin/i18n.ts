import { useTranslation } from 'react-i18next';

// Textos do twin (pt-BR + en), locais para não tocar nos arquivos de tradução do upstream.
const STRINGS = {
  pt: { homing: 'Homing (XYZ)', referencing: 'Posicionando…', referenceHint: 'Use com a mesa livre.', movedByHand: 'Movi à mão', unknownPosition: 'Posição desconhecida', manualEstimate: 'Posição estimada', camera: 'Câmera', twin: '3D', group: 'Visualização: câmera ou gêmeo 3D', twinLabel: 'Gêmeo digital 3D da impressora', unavailable: '3D indisponível neste navegador (WebGL).' },
  en: { homing: 'Home all axes', referencing: 'Moving to reference…', referenceHint: 'Use with a clear build plate.', movedByHand: 'Moved by hand', unknownPosition: 'Unknown position', manualEstimate: 'Estimated position', camera: 'Camera', twin: '3D', group: 'View: camera or 3D twin', twinLabel: '3D digital twin of the printer', unavailable: '3D unavailable in this browser (WebGL).' },
} as const;

export function useTwinStrings() {
  const { i18n } = useTranslation();
  return (i18n?.language || 'en').toLowerCase().startsWith('pt') ? STRINGS.pt : STRINGS.en;
}
