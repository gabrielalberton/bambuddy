import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { BellRing, BellOff, Loader2, Send, Smartphone, Plus } from 'lucide-react';
import { api } from '../../api/client';
import { Card, CardContent } from '../../components/Card';
import { Button } from '../../components/Button';
import { useAuth } from '../../contexts/AuthContext';
import { isWebPushUiEnabled } from './flags';
import { webPushApi } from './api';
import { recommendedWebPushProvider } from './recommended';
import { useWebPush, type WebPushStatus } from './useWebPush';

const STATUS_KEY: Record<WebPushStatus, string> = {
  checking: 'checking',
  unsupported: 'unsupported',
  insecure: 'insecure',
  'ios-install': 'iosInstall',
  'backend-off': 'backendOff',
  denied: 'denied',
  off: 'off',
  on: 'on',
};

/** Cartão "Notificações neste aparelho" (Configurações → Notificações). */
export function WebPushDeviceCard() {
  if (!isWebPushUiEnabled()) return null;
  return <WebPushDeviceCardInner />;
}

function WebPushDeviceCardInner() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();
  const { status, endpoint, error, busy, enable, disable, sendTest } = useWebPush();
  const [message, setMessage] = useState<string | null>(null);

  const canSeeProviders = hasPermission('notifications:read');
  const { data: providers } = useQuery({
    queryKey: ['notification-providers'],
    queryFn: api.getNotificationProviders,
    enabled: canSeeProviders && status === 'on',
  });
  const { data: devices } = useQuery({
    queryKey: ['custom-webpush-devices', endpoint],
    queryFn: () => webPushApi.devices(endpoint ?? undefined),
    enabled: status === 'on',
  });
  const hasWebPushProvider = (providers ?? []).some((p) => p.provider_type === 'webpush' && p.enabled);

  const createProvider = useMutation({
    mutationFn: () => api.createNotificationProvider(recommendedWebPushProvider(t('customWebPush.providerName'))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notification-providers'] });
      setMessage(t('customWebPush.providerCreated'));
    },
    onError: (e: Error) => setMessage(t('customWebPush.error', { error: e.message })),
  });

  if (status === 'backend-off') return null;

  const onTest = async () => {
    setMessage(null);
    const result = await sendTest();
    if (result) {
      setMessage(
        result.sent > 0
          ? t('customWebPush.testSent', { count: result.sent })
          : t('customWebPush.testFailed', { error: result.errors[0] || '—' }),
      );
      queryClient.invalidateQueries({ queryKey: ['custom-webpush-devices'] });
    }
  };

  const on = status === 'on';
  const canEnable = status === 'off';

  return (
    <Card className="mb-4" data-testid="custom-webpush-card">
      <CardContent className="py-3 space-y-3">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 shrink-0 ${on ? 'text-bambu-green' : 'text-bambu-gray'}`}>
            {on ? <BellRing className="w-5 h-5" /> : <Smartphone className="w-5 h-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-white text-sm font-medium">{t('customWebPush.title')}</p>
            <p className="text-xs text-bambu-gray">{t('customWebPush.description')}</p>
            <p
              className={`text-xs mt-1 ${on ? 'text-bambu-green' : status === 'denied' || status === 'insecure' ? 'text-amber-400' : 'text-bambu-gray'}`}
              data-testid="custom-webpush-status"
            >
              {t(`customWebPush.status.${STATUS_KEY[status]}`)}
            </p>
            {status === 'denied' && <p className="text-xs text-bambu-gray mt-1">{t('customWebPush.deniedHelp')}</p>}
            {on && devices && devices.length > 0 && (
              <p className="text-xs text-bambu-gray mt-1">{t('customWebPush.devices', { count: devices.length })}</p>
            )}
          </div>
        </div>

        {(canEnable || on) && (
          <div className="flex flex-col sm:flex-row gap-2">
            {canEnable && (
              <Button className="w-full sm:w-auto justify-center min-h-11" onClick={() => void enable()} disabled={busy}>
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <BellRing className="w-4 h-4" />}
                {t('customWebPush.enable')}
              </Button>
            )}
            {on && (
              <>
                <Button className="w-full sm:w-auto justify-center min-h-11" onClick={() => void onTest()} disabled={busy}>
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  {t('customWebPush.test')}
                </Button>
                <Button
                  variant="secondary"
                  className="w-full sm:w-auto justify-center min-h-11"
                  onClick={() => void disable()}
                  disabled={busy}
                >
                  <BellOff className="w-4 h-4" />
                  {t('customWebPush.disable')}
                </Button>
              </>
            )}
          </div>
        )}

        {on && canSeeProviders && providers && !hasWebPushProvider && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
            <p className="text-xs text-amber-200">{t('customWebPush.noProvider')}</p>
            {hasPermission('notifications:create') && (
              <Button
                size="sm"
                variant="secondary"
                className="w-full sm:w-auto justify-center min-h-10"
                onClick={() => createProvider.mutate()}
                disabled={createProvider.isPending}
              >
                {createProvider.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                {t('customWebPush.createProvider')}
              </Button>
            )}
          </div>
        )}

        {(message || error) && (
          <p className="text-xs text-bambu-gray break-words" role="status">
            {message || t('customWebPush.error', { error })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
