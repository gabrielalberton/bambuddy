// Bambuddy (fork gabriel): Web Push no service worker.
// Carregado pelo sw.js do upstream com uma linha:
//   try { importScripts('/custom/sw-push.js'); } catch (e) {}
// Ver custom/docs/notificacoes-pwa.md.
/* eslint-disable no-restricted-globals */
(function () {
  var DEFAULT_ICON = '/img/android-chrome-192x192.png';
  var DEFAULT_BADGE = '/custom/webpush-badge.png';

  function parsePayload(event) {
    if (!event.data) return null;
    try {
      return event.data.json();
    } catch (e) {
      try {
        var text = event.data.text();
        return text ? { title: 'Bambuddy', body: text } : null;
      } catch (e2) {
        return null;
      }
    }
  }

  // Só caminhos da mesma origem: a notificação nunca abre site de terceiros.
  function safePath(url) {
    try {
      var u = new URL(url || '/', self.location.origin);
      if (u.origin !== self.location.origin) return '/';
      return u.pathname + u.search + u.hash;
    } catch (e) {
      return '/';
    }
  }

  function buildNotification(data) {
    // Sem payload (ou payload ilegível) a notificação ainda tem que aparecer: o Chrome
    // exige showNotification em todo push e mostra um aviso genérico se faltar.
    data = data || {};
    var title = data.title || 'Bambuddy';
    var options = {
      body: data.body || (data.title ? '' : 'Nova notificação do Bambuddy'),
      icon: data.icon || DEFAULT_ICON,
      badge: data.badge || DEFAULT_BADGE,
      tag: data.tag || undefined,
      renotify: !!(data.tag && data.renotify),
      requireInteraction: !!data.requireInteraction,
      timestamp: typeof data.timestamp === 'number' ? data.timestamp : Date.now(),
      data: {
        url: safePath(data.url),
        event: data.event || null,
        printer_id: data.printer_id == null ? null : data.printer_id,
      },
    };
    if (data.image) options.image = safePath(data.image);
    return { title: title, options: options };
  }

  self.addEventListener('push', function (event) {
    var n = buildNotification(parsePayload(event));
    event.waitUntil(self.registration.showNotification(n.title, n.options));
  });

  self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    var path = safePath(event.notification.data && event.notification.data.url);
    var target = new URL(path, self.location.origin).href;
    event.waitUntil(
      self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
        // Prefere uma janela do PWA já aberta: foca e navega (sem abrir outra aba).
        for (var i = 0; i < clients.length; i++) {
          var client = clients[i];
          if (new URL(client.url).origin !== self.location.origin) continue;
          return client.focus().then(function (focused) {
            var c = focused || client;
            if (c.url === target || !('navigate' in c)) return c;
            return c.navigate(target).catch(function () {
              // navigate() falha em cliente não controlado: avisa a página para rotear sozinha.
              c.postMessage({ type: 'custom-webpush-navigate', url: path });
              return c;
            });
          });
        }
        return self.clients.openWindow(target);
      }),
    );
  });

  // Inscrição trocada pelo navegador (chave expirada etc.): a página refaz a inscrição
  // quando abrir (useWebPush confere a cada carga). Aqui só não deixamos o evento morrer.
  self.addEventListener('pushsubscriptionchange', function () {});

  self.__bambuddyWebPush = { version: 1, buildNotification: buildNotification, safePath: safePath };
})();
