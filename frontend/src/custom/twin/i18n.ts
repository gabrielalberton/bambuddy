import { useTranslation } from 'react-i18next';

// Textos do twin (pt-BR + en), locais para não tocar nos arquivos de tradução do upstream.
const STRINGS = {
  pt: { camera: 'Câmera', twin: '3D', group: 'Visualização: câmera ou gêmeo 3D', twinLabel: 'Gêmeo digital 3D da impressora', unavailable: '3D indisponível neste navegador (WebGL).' },
  en: { camera: 'Camera', twin: '3D', group: 'View: camera or 3D twin', twinLabel: '3D digital twin of the printer', unavailable: '3D unavailable in this browser (WebGL).' },
} as const;

export function useTwinStrings() {
  const { i18n } = useTranslation();
  return (i18n?.language || 'en').toLowerCase().startsWith('pt') ? STRINGS.pt : STRINGS.en;
}
