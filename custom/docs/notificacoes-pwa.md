# Notificações no PWA (Web Push)

Notificações nativas do Bambuddy no celular (PWA instalado no Android/Chrome), **inclusive com o app
fechado**, sem serviço externo (ntfy, Telegram etc.). Implementado só em código do fork; ver os pontos de
contato em `custom/CUSTOMIZATIONS.md` (seção "Web Push").

## Como funciona

1. O servidor tem um par de chaves VAPID gerado na primeira vez em
   `<DATA_DIR>/custom/webpush/vapid.json` (no container: `/app/data/custom/webpush/vapid.json`, modo 600,
   diretório 700). É segredo: fica só no volume de dados, nunca no git nem em log. Se for apagado, um novo é
   gerado e os aparelhos se reinscrevem sozinhos na próxima vez que o app abrir.
2. No aparelho, "Ativar neste aparelho" pede a permissão de notificação, cria a inscrição de push no
   navegador (FCM, no Android) e a registra no Bambuddy (`POST /api/v1/custom/webpush/subscribe`, tabela
   `custom_webpush_subscriptions`, ligada ao usuário logado).
3. Um provedor de notificação do tipo **"Web Push (PWA)"** (Configurações → Notificações → Provedores) liga
   esse canal aos eventos do Bambuddy. Valem todas as regras do upstream: eventos marcados no provedor,
   modelos de mensagem, horário silencioso, resumo diário, foto da câmera ("anexar foto").
4. Em cada evento o servidor cifra a mensagem (RFC 8291, `aes128gcm`), assina com VAPID (RFC 8292) e manda
   para o serviço de push de cada aparelho inscrito. Inscrição que volta 404/410 (desinstalou, limpou dados,
   expirou) é apagada sozinha.
5. No aparelho, o service worker (`/custom/sw-push.js`, carregado pelo `sw.js` do upstream) mostra a
   notificação. Tocar nela abre o app na página certa: impressão concluída/falhou/parada → arquivo da
   impressão; fila → Fila; filamento/estoque → Inventário; manutenção → Manutenção; demais → Impressoras.

Detalhes do payload: título, texto, ícone do app, badge monocromático, `tag` por impressora+evento (o
"progresso 50%" substitui o "25%" em vez de empilhar), horário, link e, com "anexar foto", a foto da câmera
(caminho relativo `/api/v1/notifications/photos/<nome-aleatório>`, o mesmo armazenamento que o upstream usa
para HA/Bark: nome não adivinhável e expira sozinho). Falha, parada, erro (HMS), mesa a limpar e fila
esperando vão com urgência alta e ficam na tela até tocar.

## Passo a passo no celular (Gabriel)

1. Abra o PWA do Bambuddy instalado (ou o Chrome em **https://bambu.local.alberton.work**). Tem que ser o
   endereço **https://**: por `http://100.81.104.50:...` (IP do Tailscale) o navegador não permite push.
2. Aparece no topo "Receber os alertas de impressão neste aparelho?" → **Ativar** → **Permitir**.
   (Se dispensou o convite: Configurações → Notificações → cartão "Notificações neste aparelho" →
   **Ativar neste aparelho**.)
3. No mesmo cartão, toque **Enviar teste**: deve chegar "Bambuddy: teste" em segundos.
4. Ainda no cartão, se aparecer o aviso amarelo, toque **Criar canal Web Push (eventos recomendados)**. Isso
   cria o provedor "Celular (Web Push)" com os eventos abaixo; ajuste depois em Provedores (horário silencioso
   etc.). Basta um provedor para todos os aparelhos ativados.
5. Teste com o app fechado: feche o PWA (tire dos recentes) e use "Testar" no provedor a partir do computador.

### Eventos recomendados

Ligados pelo botão do passo 4 (`frontend/src/custom/webpush/recommended.ts`):

| Evento | Por quê |
|---|---|
| Impressão concluída | tirar a peça |
| Impressão falhou | agir rápido |
| Impressão parada/cancelada | saber que parou |
| Erro da impressora (HMS) | inclui fim de filamento / AMS, entupimento etc. |
| Filamento baixo | trocar antes de acabar |
| Mesa precisa ser limpa (plate clear) | a fila depende disso |
| Fila: trabalho esperando | precisa de ação para seguir |
| Fila: trabalho falhou | idem |

Deixados desligados: início, progresso, primeira camada, mesa esfriou, impressora offline (ruído). Ligue no
provedor se quiser.

## Problemas comuns

- **Não chega nada com o app fechado (Android)**: Configurações do Android → Apps → Bambuddy (ou Chrome) →
  Bateria → **Sem restrições**. Economia de bateria agressiva atrasa/descarta push.
- **Botão não aparece / "bloqueadas"**: a permissão foi negada. Segure o ícone do Bambuddy → Informações do
  app → Notificações → Permitir (no Chrome: cadeado na barra → Permissões → Notificações) e recarregue.
- **"Push exige HTTPS"**: está aberto por IP/http. Use https://bambu.local.alberton.work (ou
  https://bambu.alberton.work). Cada origem é uma inscrição separada.
- **Teste diz "Nenhum aparelho inscrito"**: ative no aparelho primeiro (passo 2).
- **Provedor com erro "Nenhum aparelho inscrito"** no registro: nenhum aparelho ativado no momento do evento.
- **Notificação abre a página errada / não abre**: o link sempre é da mesma origem em que o app foi
  instalado; links externos viram "/".
- **iPhone/iPad**: só funciona com o Bambuddy adicionado à Tela de Início (iOS 16.4+), aberto por lá.
- **Trocou o `vapid.json`** (restore de backup antigo etc.): as inscrições antigas param; ao abrir o app em
  cada aparelho ele se reinscreve sozinho.

## Interruptores e operação

- `BAMBUDDY_CUSTOM_WEBPUSH=0` (variável do container): desliga rotas e provedor (a UI some sozinha).
- `localStorage.setItem('custom.webPush', 'off')` no navegador: esconde só a UI naquele navegador.
- `BAMBUDDY_CUSTOM_WEBPUSH_SUBJECT=mailto:...` ou `https://...`: `sub` do VAPID (padrão genérico
  `mailto:webpush@bambuddy.invalid`; a Apple exige um válido sintaticamente).
- `BAMBUDDY_CUSTOM_WEBPUSH_KEY_FILE`: outro caminho para o `vapid.json` (testes).
- `BAMBUDDY_CUSTOM_WEBPUSH_ALLOW_ANY_ENDPOINT=1`: **só para teste local** (aceita endpoint http/qualquer host).
  Em produção o endpoint precisa ser https de um serviço conhecido (FCM, Mozilla, Apple, WNS) para o
  Bambuddy não virar ponte para a rede interna.
- Para outras personalizações do fork: `from backend.app.custom.webpush import notify` →
  `await notify(user_ids_ou_None, título, texto, url="/caminho", tag="...")` (direto para os aparelhos, sem
  passar pelas regras dos provedores; para respeitar eventos/horário silencioso, dispare um evento do
  `notification_service`).

## API (`/api/v1/custom/webpush`, autenticação normal do Bambuddy)

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/public-key` | chave pública VAPID (applicationServerKey) |
| POST | `/subscribe` | `{endpoint, keys: {p256dh, auth}}`: cria/renova a inscrição do usuário |
| DELETE | `/subscribe` | `{endpoint}`: remove (só a do próprio usuário) |
| GET | `/devices` | aparelhos do usuário (sem endpoint/chaves) |
| POST | `/test` | teste para os aparelhos do usuário (ou só `{endpoint}`) |

Com autenticação ligada, chave de API não serve (precisa de usuário). Arquivos estáticos do fork em
`/custom/*` (montagem com `Cache-Control: no-cache`, para o `sw-push.js` nunca ficar velho).
