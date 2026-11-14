# Imagem de produção do fork: parte da imagem oficial da MESMA release do upstream
# (custom/BASE_VERSION) e só sobrepõe o frontend compilado por custom/build.sh.
# Contexto do build: custom/.build/ (contém static/). Não use a raiz do repo como
# contexto: o .dockerignore do upstream exclui static/.
ARG BASE_VERSION=1.3.1
FROM ghcr.io/maziggy/bambuddy:${BASE_VERSION}

ARG BASE_VERSION
ARG FORK_REVISION=unknown
LABEL org.opencontainers.image.title="bambuddy-gabriel" \
      org.opencontainers.image.description="Bambuddy ${BASE_VERSION} + personalizações do fork gabriel (frontend)" \
      org.opencontainers.image.revision="${FORK_REVISION}"

# O upstream serve o SPA de /app/static (backend core/config.py). Troca o
# diretório inteiro para não sobrar asset com hash antigo.
RUN rm -rf /app/static
COPY static/ /app/static/
