# Bambuddy do Gabriel (fork personalizado)

Fork de [maziggy/bambuddy](https://github.com/maziggy/bambuddy) (AGPL-3.0) com personalizações para o homelab do Gabriel
(uma única impressora: Bambu Lab A1 + AMS Lite). Este arquivo vale para qualquer agente (Codex, Claude Code) que mexa aqui.

## Uso principal: PWA no celular

O Gabriel usa o Bambuddy **principalmente como PWA instalado no celular Android** (Chrome), aberto por
`https://bambu.local.alberton.work` (HTTPS válido; precisa ser HTTPS para service worker e push). Toda personalização:

- é projetada e conferida **primeiro em tela de celular** (~390x844, toque, sem hover, teclado virtual), depois desktop;
- funciona dentro do PWA (modo standalone, sem barra do navegador; considerar `safe-area`, voltar do Android, app em
  segundo plano/retomado, rede caindo e voltando);
- respeita o service worker do upstream (`frontend/public/sw.js`): nada de quebrar cache/atualização; ganchos nele
  só via um `importScripts` para arquivo nosso;
- **notificações têm que chegar no PWA** (Web Push, inclusive com o app fechado) — toda funcionalidade nova que
  gere alerta precisa disparar notificação por esse canal e ser testada nele. Ver `custom/CUSTOMIZATIONS.md`.

## Premissa número 1: atualizar para uma nova release do upstream tem que ser fácil

Toda personalização existe para sobreviver a `git rebase` sobre a próxima release **com o mínimo possível de conflitos**.
Antes de escrever qualquer linha, escolha a forma que menos encosta em arquivos do upstream. Na dúvida entre "mais elegante"
e "menos conflito", vence **menos conflito**.

### Regras

1. **Código novo em arquivo novo**, sempre em diretórios só nossos (o upstream nunca vai mexer neles):
   - frontend: `frontend/src/custom/`
   - backend: `backend/app/custom/`
   - build, deploy, docs e scripts do fork: `custom/` (raiz)
   - testes: `frontend/src/custom/__tests__/` e `backend/tests/custom/`
2. **Arquivo do upstream só recebe "ganchos"**: o menor diff possível que chama código nosso (um `import` + uma condição,
   um `<Componente>` trocado, um `if (singlePrinter) return`). Lógica, estilos, textos e estado ficam no arquivo novo.
   Meta: 1-3 linhas por ponto de contato. Nunca mais de ~10 sem justificar em `custom/CUSTOMIZATIONS.md`.
3. **Prefira composição a edição**: wrapper em volta do componente original, hook próprio, alias de módulo no Vite,
   CSS próprio, router FastAPI novo incluído por uma única linha. Copiar um arquivo inteiro do upstream para alterá-lo
   é proibido (vira um fork silencioso que nunca mais recebe correções).
4. **Não "arrume" código do upstream de passagem**: sem reformatar, renomear, reordenar imports, mudar indentação,
   rodar formatter/linter com `--fix` em arquivo do upstream, nem atualizar dependências ou lockfiles
   (`package-lock.json`, `requirements*.lock`). Bug do upstream vira issue/PR no upstream, não commit aqui.
5. **Ganchos ancorados em código estável**: encoste em linhas com pouca chance de mudar (assinatura de componente,
   `return (` principal, import), não no meio de blocos que o upstream mexe toda semana.
6. **Textos (i18n)**: não editar os arquivos de tradução do upstream; textos novos ficam em `frontend/src/custom/i18n/`
   e são mesclados por um gancho.
7. **Tudo atrás de uma condição explícita**: cada personalização tem um interruptor (detecção automática ou flag
   em `frontend/src/custom/flags.ts` / variável de ambiente `BAMBUDDY_CUSTOM_*`) para poder ser desligada sem reverter
   commit e para isolar o efeito quando algo quebrar depois de uma atualização.
8. **Banco de dados**: nada de migração/coluna nova em tabela do upstream. Se precisar persistir algo, tabela nova
   com prefixo `custom_` ou chave própria em `settings` com prefixo `custom_`.
9. **Inventário obrigatório**: todo ponto de contato com arquivo do upstream é registrado em
   `custom/CUSTOMIZATIONS.md` (arquivo, âncora, o que faz, por quê). Ao atualizar, é por essa lista que se confere
   o que pode ter quebrado.
10. **Commits pequenos e temáticos**, prefixo `custom(<área>): ...`, um assunto por commit (facilita rebase e `git
    revert`). Nunca misture commit nosso com código do upstream.

## Branches e atualização

- `main`: espelho do `upstream/main`. **Nunca** commitar nela (use "Sync fork" no GitHub ou
  `git fetch upstream && git push origin upstream/main:main`).
- `gabriel`: release estável do upstream + nossos commits por cima. É dela que sai a imagem em produção.
- Atualizar para a release `vNOVA` (a base atual está em `custom/BASE_VERSION`):
  ```bash
  git fetch upstream --tags
  git switch gabriel
  git rebase --onto vNOVA "$(cat custom/BASE_VERSION)" gabriel
  echo vNOVA > custom/BASE_VERSION   # commit "custom(base): vNOVA"
  # conferir custom/CUSTOMIZATIONS.md ponto a ponto, rodar os testes, build, deploy
  git push --force-with-lease origin gabriel
  ```
  Releases `*-daily.*`/`b` (beta) não servem de base; só tags estáveis (`vX.Y.Z`).

## Build e deploy

- A imagem de produção parte da imagem oficial da mesma release e só sobrepõe o que é nosso (frontend compilado e
  arquivos do backend), ver `custom/` (Dockerfile e script de build). Não reimplementar o Dockerfile do upstream.
- Processos pesados (npm ci/build, docker build, testes de navegador) sempre com limite de memória, um por vez:
  `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=1G --nice=10 -- <comando>`.
- O deploy é o stack `23-bambuddy.yml` em `/home/gabriel/Área de trabalho/compose-migration` (ler o `AGENTS.md` de lá).
  A impressora pode estar imprimindo: reiniciar o Bambuddy não para a impressão, mas confira o estado antes e avise.
- Mudança testada e publicada: `npm run build` + testes do frontend que encostam no que mudou + testes nossos, e conferir
  a tela no navegador antes do deploy.

## Personalizações

O que cada uma faz e quais arquivos do upstream ela toca: `custom/CUSTOMIZATIONS.md`.
