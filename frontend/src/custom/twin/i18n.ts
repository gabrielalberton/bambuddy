import { useTranslation } from 'react-i18next';

// Textos do twin (pt-BR + en), locais para não tocar nos arquivos de tradução do upstream.
const STRINGS = {
  pt: { compareCamera: 'Comparar com câmera', comparingCamera: 'Comparando…', visualResult: { divergent: '3D diferente da câmera', visually_close: 'Sem desvio visual grande', unknown: 'Comparação inconclusiva' }, homing: 'Homing (XYZ)', movedByHand: 'Movi à mão', unknownPosition: 'Posição desconhecida', manualEstimate: 'Posição estimada', camera: 'Câmera', twin: '3D', group: 'Visualização: câmera ou gêmeo 3D', twinLabel: 'Gêmeo digital 3D da impressora', unavailable: '3D indisponível neste navegador (WebGL).' },
  en: { compareCamera: 'Compare with camera', comparingCamera: 'Comparing…', visualResult: { divergent: '3D differs from camera', visually_close: 'No large visual difference', unknown: 'Comparison inconclusive' }, homing: 'Home all axes', movedByHand: 'Moved by hand', unknownPosition: 'Unknown position', manualEstimate: 'Estimated position', camera: 'Camera', twin: '3D', group: 'View: camera or 3D twin', twinLabel: '3D digital twin of the printer', unavailable: '3D unavailable in this browser (WebGL).' },
} as const;

export function useTwinStrings() {
  const { i18n } = useTranslation();
  return (i18n?.language || 'en').toLowerCase().startsWith('pt') ? STRINGS.pt : STRINGS.en;
}
