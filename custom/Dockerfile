# Imagem de produção do fork: parte da imagem oficial da MESMA release do upstream
# (custom/BASE_VERSION) e só sobrepõe o que é nosso:
#   - frontend compilado por custom/build.sh (static/);
#   - backend nosso (backend/app/custom/), copiado para backend_custom/ no contexto.
# Nenhum arquivo do upstream é copiado: as rotas do fork entram pelo módulo ASGI
# backend.app.custom.asgi (importa backend.app.main.app e registra os routers),
# e o CMD abaixo é o do upstream trocando só o módulo.
# Contexto do build: custom/.build/. Não use a raiz do repo como contexto: o
# .dockerignore do upstream exclui static/.
ARG BASE_VERSION=1.3.1
FROM ghcr.io/maziggy/bambuddy:${BASE_VERSION}

ARG BASE_VERSION
ARG FORK_REVISION=unknown
LABEL org.opencontainers.image.title="bambuddy-gabriel" \
      org.opencontainers.image.description="Bambuddy ${BASE_VERSION} + personalizações do fork gabriel (frontend + backend/app/custom)" \
      org.opencontainers.image.revision="${FORK_REVISION}"

# O upstream serve o SPA de /app/static (backend core/config.py). Troca o
# diretório inteiro para não sobrar asset com hash antigo.
RUN rm -rf /app/static
COPY static/ /app/static/

# Backend nosso (pacote novo; não sobrescreve nada do upstream).
RUN rm -rf /app/backend/app/custom
COPY backend_custom/ /app/backend/app/custom/

# Mesmo CMD do Dockerfile do upstream (conferir a cada nova base!), só com
# backend.app.custom.asgi:app no lugar de backend.app.main:app. O ENTRYPOINT
# (docker-entrypoint.sh: PUID/PGID + gosu) continua o do upstream.
# Para desligar só o catálogo sem trocar imagem: BAMBUDDY_CUSTOM_MODELS_CATALOG=0.
CMD ["sh", "-c", "exec uvicorn backend.app.custom.asgi:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --loop asyncio --timeout-graceful-shutdown ${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN}"]
