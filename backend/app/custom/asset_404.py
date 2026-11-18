"""custom(chunk-recovery): 404 de /assets/* nunca fica em cache.

O 404 do upstream sai com ``Cache-Control: max-age=14400``. Um navegador ou o Cloudflare que pedir um arquivo
de build durante um deploy guarda o 404 por 4 h, e a tela que depende dele quebra mesmo depois de recarregar.
"""

from __future__ import annotations


class Asset404NoStoreMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/assets/"):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message.get("type") == "http.response.start" and message.get("status") == 404:
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
