// Textos do fork (pt-BR). Mesclados no i18n do upstream por ./index.ts.
const ptBR = {
  customPrintHistory: {
    history: 'Histórico', files: 'Arquivos', calendar: 'Calendário', filters: 'Filtros', sort: 'Ordenar',
    ascending: 'Ordem crescente', descending: 'Ordem decrescente',
    untitled: 'Trabalho #{{id}}', beforeStart: 'Antes da impressão', queueRecord: 'Registro da fila',
    loadFailed: 'Não foi possível carregar o histórico de impressão.',
    removeQueueConfirm: 'Remover este trabalho do histórico da fila?',
  },
  nav: { archives: 'Impressos' },
  archives: { page: { title: 'Impressos', allArchives: 'Todos os impressos' } },
  notifications: {
    providerTypes: { webpush: 'Web Push (PWA)' },
    providerDescriptions: {
      webpush:
        'Notificações nativas nos celulares/computadores em que o Bambuddy está instalado como app. Ative cada aparelho em Configurações → Notificações → "Notificações neste aparelho". Envia para todos os aparelhos ativados.',
    },
  },
  customWebPush: {
    title: 'Notificações neste aparelho',
    description: 'Receba os alertas do Bambuddy neste celular ou computador, mesmo com o app fechado.',
    status: {
      checking: 'Verificando…',
      unsupported: 'Este navegador não suporta notificações push.',
      insecure: 'Push exige HTTPS. Abra o Bambuddy pelo endereço https:// (não por IP nem http://).',
      iosInstall: 'No iPhone/iPad, primeiro adicione o Bambuddy à Tela de Início (Compartilhar → Adicionar à Tela de Início) e abra por lá.',
      backendOff: 'O push está desligado neste servidor.',
      denied: 'As notificações estão bloqueadas para este site. Libere nas configurações do navegador/app e recarregue.',
      off: 'Desligado neste aparelho.',
      on: 'Ligado: este aparelho recebe notificações.',
    },
    deniedHelp:
      'Android: segure o ícone do Bambuddy → Informações do app → Notificações → Permitir. No Chrome: cadeado na barra de endereço → Permissões → Notificações.',
    enable: 'Ativar neste aparelho',
    disable: 'Desativar',
    test: 'Enviar teste',
    testSent: 'Teste enviado para {{count}} aparelho(s).',
    testFailed: 'O teste falhou: {{error}}',
    devices: '{{count}} aparelho(s) ativado(s) na sua conta',
    noProvider:
      'Ainda não há canal "Web Push (PWA)" ativo: os eventos do Bambuddy só chegam a este aparelho depois que o canal existir.',
    createProvider: 'Criar canal Web Push (eventos recomendados)',
    providerCreated: 'Canal criado. Ajuste os eventos em Provedores.',
    providerName: 'Celular (Web Push)',
    bannerText: 'Receber os alertas de impressão neste aparelho?',
    bannerEnable: 'Ativar',
    bannerDismiss: 'Agora não',
    error: 'Erro: {{error}}',
  },
  custom: {
    prefs: {
      nozzleTitle: 'Bico configurado (toque para trocar)',
      nozzleHint: 'Qual bico está montado?',
      nozzleBusy: 'Não dá para trocar o bico durante a impressão',
      nozzleSet: 'Bico configurado: {{d}} mm',
      speedDefaultTitle: 'Velocidade da próxima impressão',
      speedNowHint: 'Muda agora',
      speedNextHint: 'Vale para a próxima impressão, a partir da camada {{layer}}',
      speedNow: 'Velocidade: {{mode}}',
      speedNext: 'Próxima impressão em {{mode}}',
    },
  },
};

export default ptBR;
