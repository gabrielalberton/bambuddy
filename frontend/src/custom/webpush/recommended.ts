import type { NotificationProviderCreate } from '../../api/client';

/**
 * Eventos recomendados para o canal Web Push do Gabriel (custom/docs/notificacoes-pwa.md):
 * concluída, falhou, parada, erro da impressora (HMS — inclui fim de filamento), filamento
 * baixo, mesa precisa ser limpa e fila esperando ação. O resto fica desligado (o padrão do
 * upstream liga só concluída/falhou/parada).
 */
export function recommendedWebPushProvider(name: string): NotificationProviderCreate {
  return {
    name,
    provider_type: 'webpush',
    enabled: true,
    config: {},
    attach_photo: true,
    on_print_start: false,
    on_print_complete: true,
    on_print_failed: true,
    on_print_stopped: true,
    on_print_progress: false,
    on_printer_offline: false,
    on_printer_error: true,
    on_filament_low: true,
    on_plate_clear_required: true,
    on_queue_job_waiting: true,
    on_queue_job_failed: true,
  };
}
