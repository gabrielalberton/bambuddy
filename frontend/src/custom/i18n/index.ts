/**
 * Textos do fork mesclados no i18n do upstream sem editar os arquivos de tradução dele.
 *
 * O inglês já vem embutido (resources do init) e é mesclado na hora. Os outros idiomas o
 * upstream carrega sob demanda (localeBackend); mesclar antes faria o i18next achar que
 * o idioma já está carregado e pular o arquivo do upstream, então mesclamos no evento
 * 'loaded', que dispara antes do 'languageChanged' que redesenha a interface.
 */
import i18n from '../../i18n';
import en from './en';
import ptBR from './pt-BR';

const CUSTOM: Record<string, object> = { en, 'pt-BR': ptBR };

export function mergeCustomTranslations(lng: string): void {
  const resources = CUSTOM[lng];
  if (!resources || !i18n.hasResourceBundle(lng, 'translation')) return;
  i18n.addResourceBundle(lng, 'translation', resources, true, true);
}

i18n.on('loaded', (loaded: Record<string, unknown>) => {
  Object.keys(loaded || {}).forEach(mergeCustomTranslations);
});
Object.keys(CUSTOM).forEach(mergeCustomTranslations);

export default i18n;
