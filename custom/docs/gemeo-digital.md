# Gêmeo digital da A1 dentro do Bambuddy (`custom(twin)`)

Porte do twin avulso (`~/projects/3d-printing/twin`, doc em `3d-printing/docs/tools/digital-twin.md`) para o fork.
Onde o Bambuddy mostra a câmera da A1 aparece uma chave **"Câmera | 3D"** no rodapé do quadro; em "3D" o vídeo dá
lugar a uma cena Three.js que reproduz em tempo real a posição do cabeçote, da mesa e do eixo Z e o objeto sendo
impresso. **Somente leitura**: o twin não manda nada para a impressora.

## Onde aparece

| Tela | Chave | Observação |
|---|---|---|
| Visualizador embutido (janela flutuante; é o que o PWA usa) | rodapé do quadro, centro | some com a janela minimizada |
| Página da câmera (`/camera/:id`) | rodapé da tela (`fixed`, com `safe-area`) | ao alcance do polegar no celular |
| Cartão da impressora | — | o cartão não tem vídeo (só a miniatura do job); nada a trocar |

A escolha fica salva no navegador (`localStorage['custom.twin.view']` = `camera`/`twin`) e vale para todas as telas.
Só aparece para impressoras A1 (`A1`/`N2S`; a A1 Mini é outra máquina). No modo 3D o `<img>` do MJPEG é desmontado
(o stream da câmera fecha) e a checagem de travamento do stream fica pausada.

## Arquitetura

```
A1 ──MQTT (conexão ÚNICA, do Bambuddy)──► BambuMQTTClient ──register_raw_message_handler()──► TwinHub (por impressora)
                                           PrinterState (semente ao anexar)                    │  lista branca (state.py)
Arquivo/biblioteca do Bambuddy (3MF em disco) ──► processo spawn: gcode.py + pack.py ──► cache │  since_pr, job
                                                                                               ▼
GET /api/v1/custom/twin/stream/{id}/events   SSE (token de stream da câmera)       ◄── navegador: engine.js
GET /api/v1/custom/twin/stream/{id}/job/{j}  pacote binário gzip                      sync.js (estimador) → Three.js
GET /api/v1/custom/twin/stream/{id}/model.glb  GLB opcional (404 = procedural)        geom-worker (objeto)
GET /api/v1/custom/twin/{id}/health          saúde, camera:view por cabeçalho
```

- Backend: `backend/app/custom/twin/` — `gcode.py`, `pack.py`, `state.py`, `sim.py`, `recorder.py` portados quase sem
  mudança; `jobs.py` (resolução local do 3MF, parse fora do processo, cache), `hub.py` (estado + SSE), `router.py`
  (rotas + `include_twin(app)`). Registro: `backend/app/custom/api.py` (`install()`), usado por
  `backend.app.custom.asgi:app`, que é o que a imagem do fork roda. Zero linhas em `main.py`.
- Frontend: `frontend/src/custom/twin/` — `engine/` (porte do `web/js/`; só o import do `three` mudou, `main.js` virou
  `engine.js` com `createTwin()`/`dispose()`), `DigitalTwinView.tsx` (carregado sob demanda: three.js não pesa na tela
  da câmera), `CameraOrTwin.tsx`, `TwinSwitch.tsx`, `useTwinView.ts`, `twinFlags.ts`, `i18n.ts` (pt-BR/en locais).

### Fontes de dados

- **Estado**: o handler cru do cliente MQTT do próprio Bambuddy (API pública usada pela ponte da impressora virtual),
  filtrado no tópico `device/<serial>/report`, só `json.loads` na thread do paho e repasse ao event loop. Todos os
  campos que o estimador usa chegam crus como antes (`mc_percent`, `mc_remaining_time`, `layer_num`, `gcode_state`,
  `spd_mag`/`spd_lvl`, `ams_status`, `ams.tray_now`, temperaturas e alvos, `stg`/`stg_cur`, `mc_print_sub_stage`,
  `home_flag`, `gcode_file`/`subtask_name`). Ao anexar (e a cada troca de cliente, ex. reconexão), o estado é semeado
  pelo `PrinterState` do Bambuddy (já fundido: a A1 só manda deltas); `spd_mag`/`home_flag` vêm do último `raw_data`.
  `since_pr` só existe depois da primeira mudança de P/R observada (o hub nasce no primeiro acesso ao twin, ver limites).
- **Sem publish**: o twin avulso mandava `pushall`; aqui o Bambuddy já faz o dele e o twin não publica nada (teste
  estático + teste com cliente falso garantem).
- **G-code**: `running_print_archive()` do upstream (subtask_id/arquivo vinculado), depois arquivo por nome nesta
  impressora, depois biblioteca por nome; o 3MF é lido do disco (`to_absolute_path`). **Sem FTPS próprio**: se o
  Bambuddy não arquivou o job, o FTPS dele já falhou e repetir daqui só dobraria conexões na A1.
- **Flags do firmware**: inferidas do `stg` anunciado (8 = calibração de extrusão, 1 = nivelamento), como antes.
- **Gravações (recorder)**: mantidas, mas **desligadas** por padrão (`BAMBUDDY_CUSTOM_TWIN_RECORD=1` liga; JSONL em
  `<data>/custom/twin/recordings`, 200 MB no máximo, recusa linhas com access code/serial).

### Memória

O parser roda num processo `spawn` separado (um por vez, encerrado ao fim), então o pico não fica no processo do
Bambuddy. Medido (pico do processo filho, `ru_maxrss`):

| G-code | linhas | registros | pico | tempo |
|---|---|---|---|---|
| Stack Matrix 256 | 72 mil | 55 mil | 43 MB | 0,8 s |
| `/tmp/shelf1/out/s.gcode.3mf` | 386 mil | 255 mil | 75 MB | 3,8 s |
| earth (16 h) | 677 mil | 443 mil | 77 MB | 6,3 s |

O pacote fica em memória só gzip (0,4–2,8 MB) e em disco em `<data>/custom/twin/cache` (8 arquivos / 200 MB no
máximo). O `mem_limit` atual do container (768 MiB, ~280 MiB em uso) comporta com folga.

## Interruptores

- Backend: `BAMBUDDY_CUSTOM_TWIN=0` desliga as rotas (404).
- Frontend: `frontend/src/custom/twin/twinFlags.ts` (`TWIN_VIEW`), ou no navegador
  `localStorage.setItem('custom.twin', 'off')`. Nos testes do vitest fica desligado (a suíte do upstream não muda).
- Ajustes por URL da página (sem UI): `?twinDebug` (expõe `window.__twin`), `?twinModel=procedural`, `?twinLead=0.8`.
- Simulação (dev/QA, nunca toca na impressora): `BAMBUDDY_CUSTOM_TWIN_SIM=<arquivo.gcode.3mf>`,
  `BAMBUDDY_CUSTOM_TWIN_SIM_START=<min>`, `BAMBUDDY_CUSTOM_TWIN_SIM_SPEED=<x>`.

## Autorização

Igual à da câmera: `events`, `job` e `model.glb` exigem o token de stream (`POST /printers/camera/stream-token`,
permissão `camera:view`, escopo de impressoras de quem gerou) em `?token=`, porque `EventSource` não manda
cabeçalho; o SSE reconfere a cada 30 s se quem abriu ainda pode ver (como o MJPEG). O middleware global do upstream só
"sai da frente" para o prefixo `/api/v1/custom/twin/stream/` (entrada adicionada em tempo de execução em
`PUBLIC_API_PREFIXES` por `include_twin`; se o upstream renomear a lista, as rotas passam a dar 401: falha fechada).
`health` fica atrás do middleware e exige `camera:view` por cabeçalho. Só GET (POST/PUT/PATCH/DELETE = 405). O SSE
leva só a lista branca (`state.PUBLIC_KEYS`): nada de IP, serial, access code, SSID ou URL de câmera.

## Celular / PWA

- Chave com alvo de toque de 36 px, no rodapé (polegar), `safe-area-inset-bottom` respeitado.
- `pixelRatio` no máximo 1,5x no celular (2x no desktop), adaptativo (desce até 0,75x se o FPS cair abaixo de 28).
- Loop de render pausado com a aba/PWA em segundo plano (`visibilitychange`) e com o quadro fora da tela
  (`IntersectionObserver`); no modo câmera o twin é desmontado (nada roda).
- SSE fechado em segundo plano e reaberto ao voltar, com a URL refeita (token de stream atual). Se o token vencer,
  o `EventSource` fecha com 401 e o twin reabre com backoff (1,5 s → 30 s) usando o token novo.
- `frontend/public/sw.js` não foi tocado.

## Controles de movimento

O botão **Homing (XYZ)** no painel da A1 usa o comando de homing completo do Bambuddy e mantém o painel aberto.
Com a impressora parada e os três eixos referenciados pela telemetria (`home_flag & 7 == 7`), o gêmeo antecipa
os movimentos X/Y/Z acionados neste painel, a partir da posição que já está desenhada na tela. O quadro indica
**Posição estimada** porque a A1 transmite o estado do homing, mas não as coordenadas. A estimativa é local à
página: comandos enviados pelo visor da impressora, por outro navegador ou por outro app não aparecem nela.
Falhas devolvidas pela API desfazem o avanço correspondente. Novo homing, perda da telemetria ou início de
impressão descartam a estimativa. Durante a impressão, a pose continua vindo do estimador de G-code.

## Modelo 3D da A1 (GLB opcional, NUNCA no git)

O STEP da comunidade (MakerWorld "Bambulab A1 CAD step model", vajojajo) tem **licença desconhecida**: o GLB não vai
para o repositório (o fork é público). Sem ele, o modelo procedural é usado. Para instalar no volume de dados:

```bash
# GLB gerado no 3d-printing (ver digital-twin.md, "Modelo 3D da A1")
docker cp ~/projects/3d-printing/twin/web/assets/a1.glb bambuddy:/app/data/custom/twin/a1.glb
# (ou copiar para <volume de dados>/custom/twin/a1.glb no host). Não precisa reiniciar.
```

## O que mudou em relação ao twin avulso

- Sem segunda conexão MQTT e sem `pushall`; sem chave de API nem `printer.env`; sem HTTP próprio (porta 4860).
- 3MF do disco do Bambuddy em vez da API + FTPS; parser fora do processo.
- Hub preguiçoso: começa a observar no primeiro acesso ao twin (não precisa de gancho no `lifespan`).
- Rotas sob o prefixo da API com a autenticação do Bambuddy; GLB servido do volume.
- Frontend como componente React montável/desmontável, three 0.181 do projeto (o avulso usa 0.186 vendorizado; as APIs
  usadas são as mesmas), worker pelo Vite, celular primeiro (pausa/reconexão).

## Limites

- Os mesmos do twin avulso (dead reckoning entre âncoras de ~1 min, esperas nominais, sem `mc_print_line_number`).
- `since_pr` (âncora ao entrar no meio do job) só fica disponível depois que o hub observou uma mudança de P/R: logo
  depois de reiniciar o Bambuddy, a primeira abertura do twin no meio de um job pode ficar até ~1 min menos precisa.
- O estado é o do Bambuddy: se o MQTT dele cair, o twin congela junto (`conn.mqtt=false` no SSE).
- QA de navegador feito em SwiftShader (headless, sem GPU): FPS real no celular não medido.

## Notificações (candidatas para o Web Push do PWA, a implementar à parte)

Eventos que o hub já observa e mereceriam aviso: job do twin falhou ao carregar (3MF não encontrado no
arquivo/biblioteca, `job.status=failed`); posição desconhecida (`home_flag&7 != 7`, cabeçote mexido à mão) antes de
imprimir; troca de filamento demorando muito mais que o nominal (`ams_status` parado em 258–263); twin muito fora de
sincronia (resíduo grande na âncora M73) — útil como sinal de pausa/falha não reportada.

## Testes

- `backend/tests/custom/twin/`: parser/planejador contra G-codes reais (pulam se `~/projects/3d-printing/work` não
  existir), somente leitura, lista branca, rotas/autorização, cache, parser fora do processo.
- `frontend/src/custom/__tests__/twin.test.tsx`: chave, troca do quadro nas duas telas, stream fechado, persistência,
  teclado, nenhuma checagem de travamento com o 3D ativo.
