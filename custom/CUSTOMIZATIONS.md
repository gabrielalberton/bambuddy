# Personalizações do fork (base: ver `custom/BASE_VERSION`)

Todo ponto de contato com arquivo do upstream fica listado aqui. Ao atualizar a base, confira item a item
(a âncora é o texto a procurar; números de linha mudam).

## 1. Modo impressora única (`custom(single-printer)`)

Gabriel tem uma impressora só (A1). A UI que só existe porque "poderia haver várias" some; onde o elemento também
define estado obrigatório (ex.: `printer_id`), o valor é resolvido para a única impressora.

### Interruptor

- `frontend/src/custom/flags.ts`: `SINGLE_PRINTER_MODE = 'auto' | 'on' | 'off'` (padrão `'auto'` = liga quando o usuário
  enxerga exatamente 1 impressora em `GET /printers/`).
- Sem recompilar, no navegador: `localStorage.setItem('custom.singlePrinterMode', 'off')` (ou `'on'`/`'auto'`) e recarregar.
- Nos testes (vitest, `MODE === 'test'`) o modo efetivo é `'off'`: a suíte do upstream roda sem alteração. Testes nossos
  ligam com `setSinglePrinterModeOverride()`.

### Código nosso (`frontend/src/custom/`)

| Arquivo | O que é |
|---|---|
| `flags.ts` | modo + override de teste + override por `localStorage` |
| `useSinglePrinter.ts` | `useSinglePrinter()` → `{ single, printer, printers, isLoading }` sobre a mesma query `['printers']`; guarda a última contagem em `localStorage['custom.singlePrinter.lastCount']` para não piscar enquanto carrega. `useAutoSelectSinglePrinter(when, select)` preenche um campo vazio com a única impressora (evita importar `useEffect` no arquivo do upstream). |
| `MultiPrinterOnly.tsx` | `<MultiPrinterOnly always={...}>` renderiza os filhos só fora do modo único (ou quando `always`). Permite esconder um bloco sem chamar hook no componente do upstream. |
| `useSinglePrinterCamera.ts` | `useSinglePrinterCameraToggle(open, setOpen, enabled)`: no CameraLauncher, `open=true` vira abrir/fechar a câmera da única impressora (via `useLayoutEffect`, o menu nunca pinta). Vale também para o atalho de teclado `C`. |
| `__tests__/` | hook, flags, `MultiPrinterOnly`, `useAutoSelectSinglePrinter`, toolbar da PrintersPage, PrinterSelector, CameraLauncher e PrintModal enviando com `printer_id` da única impressora. |

Não foi preciso texto novo (só escondemos coisas), então não há `frontend/src/custom/i18n/` ainda.

### Pontos de contato no upstream

Formato: arquivo — âncora — linhas (+/−) — o que/por quê. Todos importam de `../custom/...` logo abaixo de
`import { useTranslation } from 'react-i18next';` (exceto PrinterSelector e CameraLauncher, ver âncora).

| Arquivo | Âncora | +/− | O que / por quê |
|---|---|---|---|
| `pages/PrintersPage.tsx` | import; logo após `const { data: printers, isLoading } = useQuery({ queryKey: ['printers'] ...});` | +14/−5 | `const { single }` + um `useEffect` que, no modo único, zera em memória (sem gravar no `localStorage`) busca, filtro de status/local, "ocultar offline", ordenação (→ `name`, desliga agrupamento e "selecionar todos" por grupo) e força `pageView='cards'`. Isso garante que preferência salva nunca esconda a única impressora. Esconde: `<StatusSummaryBar>`, caixa de busca (`{/* Only show search bar ...*/}`), divisor + `renderFilterControls()` da barra expandida, `ToolbarMenu` de filtros da barra compacta, bloco ordenação + link `/printer-locations` + chave Cards/Cam Wall + link `/camwall` (`{!single && (<>` após `{/* Sort dropdown */}` … `</>)}` após o link camwall), botão de seleção em massa (`{/* Bulk select toggle */}`, então `BulkPrinterToolbar` nunca aparece). Desde 2026-11-14 o cabeçalho inteiro (título "Printers" + menus Visualização/Ações, que no modo único só tinham tamanho de card, "Ligar" e "Adicionar impressora") some: `<div className="space-y-3 mb-6">` vira `className={single ? 'hidden' : ...}` (o DOM continua, então o `ResizeObserver` da barra não muda; adicionar impressora segue em Configurações/modo `off`). 14 linhas: acima da meta de ~10, porque são 7 elementos independentes no mesmo arquivo. |
| `components/PrintModal/PrinterSelector.tsx` | import após `useUiSettings`; após `useState(false)` de `showAllPrinters`; `const modelAssignmentAvailable =`; `{assignmentMode === 'printer' && displayPrinters.map(` | +4/−2 | `modelAssignmentAvailable` fica falso no modo único com `assignmentMode === 'printer'` (some a chave "Specific Printer / Any <modelo>" e o seletor de modelo/local; se o item já estiver em modo modelo, a UI aparece para dar como voltar). A lista de botões some quando a única impressora já está selecionada; volta se nada estiver selecionado (para não travar o usuário). A seleção automática continua sendo a do upstream (`PrintModal/index.tsx`, efeito com `activePrinters.length === 1`), não mexemos nela. |
| `components/CameraLauncher.tsx` | import após `EmbeddedCameraContext`; após `const canView = ...` | +2 | `useSinglePrinterCameraToggle(open, setOpen, canView)`. |
| `pages/QueuePage.tsx` | import; antes de `localStorage.setItem('queue.pendingSortBy'`; `BulkEditModal` `{/* Printer Assignment */}`; linha da fila (`<span className={\`flex items-center gap-1 sm:gap-1.5 ${item.printer_id === null` …); `<option value="printer">` nos dois selects de ordenação; filtro de impressora e local; chave "Por impressora"; `activeLayout === 'position'` | +17/−4 | Some filtro de impressora/local, chave Lista/Por impressora (layout forçado em lista), opção "ordenar por impressora" (efeito troca `printer`→`position`/`date` se estava salvo), select de impressora do `BulkEditModal` e o rótulo da impressora em cada item (mantido para itens sem impressora: "Não atribuído"/"Qualquer <modelo>"). |
| `pages/ArchivesPage.tsx` | import; após `useState` de `filterPrinter` (`archiveFilterPrinter`); `visibleLogColumns`; `{printerName}` no card; `ArchiveListRow` (`useAuth()` + `col-span-4` + célula `{printerName}`); filtro "All Printers"; cabeçalho da lista; `{/* Printer filter */}` do log | +17/−8 | Efeito zera `filterPrinter` (e com isso o `localStorage['archiveFilterPrinter']` salvo). Some filtro de impressora (grade/lista e log), coluna "Printer" do cabeçalho e da linha (nome passa de `col-span-4` para `col-span-6`, grade continua somando 12), nome da impressora no card (mantido quando o arquivo não tem impressora, mostra o modelo fatiado) e coluna `printer` do log (filtrada em `visibleLogColumns`; ainda aparece no modal de colunas, sem efeito). |
| `pages/StatsPage.tsx` | `{/* Show per-printer breakdown when expanded */}`; `{printerEntries.length > 0 && (`; `{/* By Printer */}` | +7 | `<MultiPrinterOnly>` em volta das quebras por impressora de SuccessRate, TimeAccuracy e do gráfico "Por impressora". |
| `pages/SettingsPage.tsx` | bloco `{t('settings.defaultPrinter')}`; `<Card id="card-printmodal">` | +5 | Some "Impressora padrão" e o cartão "expandir mapeamento por impressora". A busca de configurações ainda lista "Print modal" (âncora `card-printmodal`), só não rola para lugar nenhum. |
| `components/QrAssignTargetModal.tsx` | `<label htmlFor="qr-printer-select"` | +3 | Esconde o select; o estado já cai em `printers[0]`. |
| `components/KProfilesView.tsx` | `{t('kProfiles.printer')}` | +3 | Esconde o select; o upstream já autoseleciona a primeira ativa. |
| `components/AddNotificationModal.tsx` | `{/* Link to Printer */}` | +3 | Esconde "vincular à impressora" (padrão = todas); continua visível se o provedor já estiver vinculado, para poder desvincular. |
| `components/NotificationProviderCard.tsx` | `{/* Linked Printer */}` | +3 | Esconde os selos "Impressora: X" / "Todas as impressoras". |
| `components/HASensorModal.tsx` | `{!isEditing && (` + `{t('haSensors.printer')}` | +3 | Esconde o select (padrão `printers[0]`); aparece se o valor estiver vazio. |
| `components/WLEDSettings.tsx` | `{t('wled.printer')}` | +3 | Esconde o select (upstream autoseleciona); aparece se vazio. |
| `components/StreamOverlayBuilder.tsx` | `htmlFor="overlay-builder-printer"` | +3 | Esconde o select (padrão `list[0]`); aparece se vazio ou se a URL importada aponta impressora desconhecida. |
| `components/VirtualPrinterAddDialog.tsx` | após `useQuery` de `printers`; `{mode === 'proxy' && (` | +5 | `useAutoSelectSinglePrinter` preenche `targetPrinterId` (só é enviado no modo proxy) e esconde o select. |
| `components/VirtualPrinterCard.tsx` | `{/* Target Printer */}` | +3 | Esconde o select quando o alvo já está definido no servidor; sem alvo, continua visível (vínculo real: herda código de acesso). |
| `components/SpoolmanSettings.tsx` | `{/* Printer selector */}` | +3 | Esconde o select de sincronização (padrão "todas"). |
| `components/OctoEverywhereSettings.tsx`, `components/ObicoSettings.tsx` | `<Card id="card-fd-perprinter">` | +3 cada | Esconde o cartão "por impressora" enquanto estiver em "monitorar todas"; se a lista estiver restrita, o cartão volta (senão não haveria como reativar). |
| `components/SlicerPipelinesPanel.tsx` | `value={targetFilter}` (filtro da lista) | +3 | Esconde o filtro por alvo (visível se houver filtro ativo). O select "Target printer" do rascunho NÃO foi tocado. |
| `pages/PipelineRunsPage.tsx` | `{(targetOptions.printers.length > 0 \|\| targetOptions.classes.length > 0) && (` | +3 | Esconde o filtro por alvo (visível se ativo). |
| `pages/MaintenancePage.tsx` | após `useMemo` de `printers` em `SettingsSection`; `{/* Printer selection */}`; `{printer.printerName}` do cartão de override | +6/−1 | Ao criar tipo de manutenção, a única impressora é selecionada sozinha e o bloco "atribuir a impressoras" some (volta se vazio). Some o nome da impressora nos cartões de intervalo. |
| `pages/InventoryPage.tsx` | `{printerLabel} {slotLabel}` (coluna `location`) | +2/−1 | Tira o prefixo do nome da impressora ("A1 AMS1-T2" → "AMS1-T2"). |

Total no upstream (`git diff --stat v1.3.1..gabriel -- . ':!custom' ':!AGENTS.md' ':!frontend/src/custom'`):
23 arquivos, +117/−20.

### Itens do inventário deixados de fora (e por quê)

- **SpoolBuddy** (TopBar, Layout, AssignToAmsModal, Dashboard, QuickMenu): fora do escopo desta fase (quiosque; o swipe já é inerte com < 2).
- **EditArchiveModal**: campo real do arquivo (qual impressora imprimiu); manter.
- **AddSmartPlugModal**: vínculo real plugue→impressora; manter.
- **Acesso às impressoras** (Settings usuários/grupos, `GroupEditPage`): permissão real; manter.
- **SystemInfoPage**: listas informativas; fora do escopo.
- **PrinterSearchPicker** (câmera externa, Settings): é a ação "adicionar câmera externa para impressora X", não um filtro; escondê-lo removeria a função. Precisaria de um botão novo; fica para depois.
- **Filtro "impressora" em ProfilesPage / OrcaCloudProfilesView**: filtra presets pelo *modelo* da impressora escolhida; com uma impressora continua útil ("só presets que servem na minha A1"). Mantido de propósito.
- **SlicerPipelinesPanel, select "Target printer" do rascunho**: escolha real entre "sem alvo" / classe / impressora; manter.
- **MaintenancePage**: cabeçalho `PrinterSection` (traz os selos de vencidos) e chips atribuir/remover tipo por impressora (função real de ligar/desligar um tipo) mantidos.
- **Rotas `/camwall` e `/printer-locations`**: continuam existindo; só os links da página de impressoras somem.

### Cabeçalhos enxutos (2026-11-14)

| Arquivo | Âncora | +/− | O que |
|---|---|---|---|
| `pages/PrintersPage.tsx` (PrinterCard) | `const { t } = useTranslation();` no início do `PrinterCard`; `<img src={getPrinterImage(printer.model)}`; `<h3 ...>{printer.name}</h3>`; `{printer.model \|\| 'Unknown Model'}`; span do bico (`• {installedNozzleDiameters...}`); texto do badge de conexão; condição `{/* WiFi signal indicator */}`; texto `{firmwareInfo.current_version}` e o span de reserva `status?.firmware_version` | +10/−9 | No modo único: sem imagem, nome e modelo (fica "0.4mm · 🕒 10h"); badge de conexão só com o ícone (Offline continua com texto); sem badge de WiFi; firmware só com o ícone (versão no `title`), sem o span de reserva. Imagem/nome ficam no DOM com `hidden` (1 linha cada). |
| `pages/CameraPage.tsx` | import após o de `../custom/twin`; após `const twinActive = useTwinActive(id);`; `{printer?.name \|\| \`Printer ${id}\`}` do `<h1>` | +3/−1 | Sem o nome da impressora no cabeçalho da câmera (apertava os botões no celular). |

## 2. Catálogo de modelos (`custom(models)`)

Aba **Catálogo** (primeira, padrão) em *Fontes de modelos* (`/model-sources?tab=catalog`), no estilo do navegador
MakerWorld do Bambu Handy: busca, fontes, ordem, categorias, detalhe com perfis, **Salvar na biblioteca** e
**Fatiar no Bambuddy** (salva e abre o `SliceModal` existente; nunca inicia impressão). Projetada primeiro para o PWA
no celular (390x844, toque): grade de 2 colunas, chips roláveis, chave grande, barra Salvar/Fatiar fixa no rodapé com
`safe-area`, estado na URL (o "voltar" do Android fecha o detalhe). Screenshots: `custom/docs/screenshots/catalogo/`.
Detalhe também mostra avaliações (nota, quantidade, comentários), estatísticas (downloads, impulsionamentos, datas por
perfil), dados por perfil (filamento, peso, tempo, placas, bico), links da descrição clicáveis (link para outro modelo
do MakerWorld abre **dentro** do catálogo), autor clicável (catálogo interno do autor, `AuthorView.tsx`) e botão **3D**
(MakerWorld: abre o GLB leve com Draco que o próprio site usa no visualizador, sem baixar o 3MF nem salvar, rota `<id>/preview/<perfil>?plate=N`, `GlbPreviewModal.tsx`; outras fontes: salva e abre o `ModelViewerModal`). O decodificador Draco fica em `frontend/public/custom/draco/` (copiado de `three/examples/jsm/libs/draco/gltf`; `draco_worker.js` é gerado do `DRACOWorker` do `DRACOLoader.js`: **refazer ao atualizar o three**). Ele roda num worker de mesma origem, e `backend/app/custom/draco_worker_csp.py` põe esse caminho na regex `_PDF_WORKER_ASSET_RE` do `main.py`: o worker recebe só `'wasm-unsafe-eval'`, e o CSP do documento continua igual. Importar por URL do MakerWorld: ícone de link
ao lado da ordenação (`ImportModal.tsx`).

Baseado no trabalho de 1337faye/bambuddy-model-search (AGPL-3.0, commit `1b3b65b59`), **portado** (não cherry-pick)
para os diretórios do fork. Ficaram de fora: tudo de X2D, o CSS das setas de select, edições nos locales do upstream,
reescrita de testes do upstream e o mecanismo de "fonte temporária" de fatiamento (exigia mexer em `library.py` e
`library_trash.py`; aqui Fatiar = salvar normal + SliceModal).

Detalhes por fonte, evidência do filtro e limites: `custom/docs/fontes-de-modelos.md`.

### Filtro "Só para minha <modelo>"

Ligado por padrão em todas as fontes; desligar fica lembrado por navegador (`localStorage['custom.models.printerFilter']`).
O modelo vem de `GET /printers/` (modo impressora única: a única; senão todos os modelos distintos); `A1` só como
fallback quando o usuário não enxerga impressora nenhuma.

| Fonte | Acesso | Busca/detalhe | Salvar/Fatiar | Filtro A1 |
|---|---|---|---|---|
| MakerWorld | search-service público + design-service (anônimo) | sim | sim, via `POST /makerworld/import` do upstream (credencial Bambu Cloud salva; permissão `makerworld:import`) | **no servidor**: `devModelNames=N2S` (perfil compatível, `compatibility` ou `otherCompatibility`); no detalhe, perfis A1 primeiro e pré-selecionado |
| Printables | GraphQL público (anônimo) | sim | sim (STL/3MF; outros só salvar) | **não aplicável** (sem dimensões nem perfis por impressora); opção explícita "impressora do autor = A1" (`printerIds`, rara) |
| Thingiverse | API oficial, **App Token** | sim (com token) | sim (com token) | não aplicável |
| Thangs, Cults3D, MyMiniFactory, Crealty Cloud | — | não implementadas (ver docs) | — | — |

### Filtro avançado e CyberBrick (2026-11-19)

Botão **Filtros** na barra (só com uma fonte selecionada) abre um modal com os filtros que a API da fonte aceita na
requisição (folha de baixo no celular; `?filters=1` na URL, então o voltar do Android fecha), agrupados, com contador no
botão, **Limpar** e **Aplicar**. Filtros ativos viram chips removíveis acima da grade; ficam lembrados por fonte em
`localStorage['custom.models.filters.<fonte>']`. A chave **CyberBrick** (MakerWorld, `model_tag=cb`) fica sempre na
barra, fora do modal, e o card mostra o selo CyberBrick. Ordenações extras por fonte (MakerWorld: curtidas, impulsos,
impressões, coleções, aleatório; Printables: avaliação, makes; Thingiverse: makes, texto) e "Mais novos" do MakerWorld
virou `orderBy=newUploads`. Esquema, parâmetros e evidência por fonte: `custom/docs/fontes-de-modelos.md` (seção
"Filtro avançado"). Backend: `GET /custom/models/<fonte>/filters` (cache 1 h) e `filters=<JSON>` no `/browse`
(fora do esquema → 400; entra na chave de cache). Thingiverse ganhou categorias (`/categories/{slug}` → `children`).
Screenshots (390x844): `~/.cache/bambuddy-qa/catalog-filters/`. **Nenhum arquivo do upstream tocado.**

### Interruptores

- Filtro avançado: `frontend/src/custom/flags.ts` → `CATALOG_FILTERS = 'on'`; no navegador
  `localStorage.setItem('custom.catalogFilters','off')` (some o botão, a chave CyberBrick e os chips; a busca volta a
  não mandar `filters`). Testes: `setCatalogFiltersOverride('on')`.
- Frontend: `frontend/src/custom/flags.ts` → `MODEL_CATALOG = 'on'`; no navegador `localStorage.setItem('custom.modelCatalog','off')`.
  Nos testes (vitest) o efetivo é `'off'` (suíte do upstream intacta); testes nossos usam `setModelCatalogOverride('on')`.
- Backend: `BAMBUDDY_CUSTOM_MODELS_CATALOG=0` não registra as rotas.
- Thingiverse: só liga com `BAMBUDDY_CUSTOM_THINGIVERSE_API_KEY` (env do container; nunca no git).

### Código nosso

| Caminho | O que é |
|---|---|
| `backend/app/custom/asgi.py` | ponto de entrada da imagem: importa `backend.app.main.app` e chama `install()` |
| `backend/app/custom/api.py` | `install(app)`: inclui os routers do fork e os move para **antes** da rota pega-tudo do SPA (`GET /{full_path:path}`) |
| `backend/app/custom/models_catalog/` | `filters.py` (esquema/validação do filtro avançado), `router.py` (`/api/v1/custom/models/{sources, <fonte>/browse, filters, categories, thumbnail, <id>, <id>/reviews, <id>/save, author/<uid>}`), `makerworld.py`, `printables.py`, `thingiverse.py`, `transport.py` (cache, allowlist de CDN, validação STL/3MF), `printer_models.py` (modelo → `devModelName`/id do Printables) |
| `backend/tests/custom/` | transporte, fontes (transporte simulado), rotas com a biblioteca real e permissões |
| `custom/scripts/smoke_models_catalog.py` | smoke ao vivo (poucas requisições, sem download) |
| `frontend/src/custom/models/` | `FiltersModal.tsx` (modal, chips, chave CyberBrick), `filters.ts` (persistência/sanitize/rótulos), `ModelCatalog.tsx`, `ModelDetail.tsx`, `catalogTab.ts` (gancho), `usePrinterModels.ts`, `api.ts`, `i18n.ts` (pt-BR/en próprio), `shared.tsx`, `constants.ts`, `utils.ts`, `types.ts` |
| `frontend/src/custom/__tests__/modelCatalog.test.tsx` | aba/flag, filtro padrão e persistência, modelo da impressora, Printables N/A, fonte sem chave, detalhe/salvar/fatiar |
| `frontend/src/custom/__tests__/modelCatalogFilters.test.tsx` | filtro avançado: flag desligada, modal/aplicar/limpar, contador, chips, persistência por fonte, CyberBrick e selo, ordens por fonte |
| `backend/tests/custom/test_models_catalog_filters.py` | esquema por fonte (cfg2/GraphQL/estático), validação, parâmetros de cada fonte, rota e chave de cache |

### Pontos de contato no upstream

| Arquivo | Âncora | +/− | O que / por quê |
|---|---|---|---|
| `frontend/src/pages/ModelSourcesPage.tsx` | import após `import { MakerworldPage }`; `type SourceTab`; após `if (showManyfold) tabs.push(...)`; antes de `{active === 'makerworld' && <MakerworldPage embedded />}` | +6/−3 | `useCatalogTab(tabs)` põe a aba em primeiro (com a flag desligada não faz nada) e `{active === 'catalog' && <CatalogTab />}`. Com o catálogo aberto, `hideSourcesHeader(active)` esconde o título e as abas (localStorage `custom.catalogSourcesHeader='on'` traz de volta). |
| `backend/app/main.py` | — | 0 | **Não tocado.** As rotas entram por `backend.app.custom.asgi` (ver Build). |

Desvio de rota conhecido: em dev local, `uvicorn backend.app.main:app` **não** tem as rotas do catálogo; use
`uvicorn backend.app.custom.asgi:app`.

## 3. Gêmeo digital da A1 (`custom(twin)`)

Chave **"Câmera | 3D"** onde o Bambuddy mostra a câmera da A1: em "3D", o quadro de vídeo dá lugar ao gêmeo digital
(porte do `3d-printing/twin`). O visualizador é somente leitura. O botão de referência usa a conexão MQTT existente. Detalhes, medições e limites:
`custom/docs/gemeo-digital.md`.

### Interruptores

- Backend: `BAMBUDDY_CUSTOM_TWIN=0` (rotas respondem 404). Gravações: `BAMBUDDY_CUSTOM_TWIN_RECORD=1` (desligado por padrão).
  Simulação de dev/QA: `BAMBUDDY_CUSTOM_TWIN_SIM=<arquivo.gcode.3mf>` (+ `_SIM_START`, `_SIM_SPEED`).
- Frontend: `frontend/src/custom/twin/twinFlags.ts` (`TWIN_VIEW`), ou `localStorage['custom.twin'] = 'off'|'on'`. Nos testes
  do vitest fica desligado (override `setTwinOverride()`). Escolha do usuário: `localStorage['custom.twin.view']`.
- GLB opcional da A1 em `<data>/custom/twin/a1.glb` (licença desconhecida: **nunca** versionar; sem ele, modelo procedural).
- Movimento manual da A1: botões **Homing (XYZ)** e **Movi à mão**, com estimativa instantânea de X/Y/Z a partir da referência absoluta comandada (ver [controles de movimento](docs/gemeo-digital.md#controles-de-movimento)).
- Placa liberada (2026-11-19): o snapshot do SSE traz `plate_wait` (= `printer_manager.is_awaiting_plate_clear`). Com `false` fora de RUNNING/PREPARE/PAUSE ("Marcar placa como liberada" depois do fim), o twin esconde a peça. A próxima impressão volta a mostrar.
- Recheio (2026-11-20): no orçamento de triângulos (celular 900 mil, desktop 2,2 mi) o recheio passa a ser o último a sair. Antes vira faixa plana (`PROFILE2`, 2 triângulos/segmento) e o perfil das paredes cai de 6 para 4 pontos (`engine/geom-build.js`, teste `twinGeom.test.ts`).
- Linha sendo depositada (2026-11-19): durante a impressão, os últimos 3 s de programa da peça brilham em laranja e esfriam para a cor do filamento (`HOT_S` em `engine/object.js`), para ver o filete saindo do bico.

### Código nosso

| Arquivo | O que é |
|---|---|
| `backend/app/custom/twin/` | `gcode.py`/`pack.py`/`state.py`/`sim.py`/`recorder.py` (portados), `jobs.py` (3MF do arquivo/biblioteca, parse em processo spawn, cache em `<data>/custom/twin/cache`), `hub.py` (estado via `register_raw_message_handler` do cliente MQTT do Bambuddy, SSE), `router.py` (rotas de visualização GET e de referência POST + `include_twin`) |
| `backend/app/custom/api.py` | `install()` chama `include_twin(app)` (2 linhas, arquivo nosso) |
| `backend/tests/custom/twin/` | parser vs G-code real, somente leitura/sem publish, lista branca, rotas e autorização |
| `frontend/src/custom/twin/` | `engine/` (motor JS portado + `engine.d.ts`), `DigitalTwinView.tsx` (lazy), `CameraOrTwin.tsx`, `TwinSwitch.tsx`, `useTwinView.ts`, `twinFlags.ts`, `i18n.ts`, `index.ts` |
| `frontend/src/custom/__tests__/twin.test.tsx` | chave, troca do quadro nas duas telas, stream fechado, persistência, teclado, sem checagem de travamento no 3D |

### Pontos de contato no upstream

| Arquivo | Âncora | +/− | O que / por quê |
|---|---|---|---|
| `frontend/src/components/EmbeddedCameraViewer.tsx` | import após `useIsSidebarCompact`; após `useState` de `isMinimized`; efeito `// Stall detection` (condição e deps); `{!isMinimized && (` do `{/* Video area */}` e o `</div>` antes de `{/* Skip Objects Modal */}` | +6/−2 | `useTwinActive` pausa a checagem de travamento do stream com o 3D ativo (senão ela "reconectaria" uma câmera desmontada); `<CameraOrTwin>` em volta do quadro de vídeo (desenha a chave no rodapé da janela e troca o quadro). |
| `frontend/src/pages/CameraPage.tsx` | import após `requestCameraPopIn`; após `useState` de `streamMode`; efeito `// Stall detection - periodically check...` (condição e deps); `<div ref={videoAreaRef}` e o `</div>` antes de `{/* Skip Objects Modal */}` | +6/−2 | Idem; a chave fica fixa no rodapé da tela (polegar, `safe-area`). |
| `frontend/src/pages/PrintersPage.tsx` | Mutações `bedJogMutation`, `xyJogMutation`, `homeAxesMutation` e painel de movimento | +28/−8 | Liga o botão de referência da A1 à rota do fork e espelha os deslocamentos locais via `custom/twin/manualMotion.ts`. |
| `frontend/src/api/client.ts` | `moveToTwinReference` ao lado de `homeAxes` | +3 | Reutiliza a autenticação do cliente para chamar a rota de referência da A1. |
| `backend/app/main.py` | `PUBLIC_API_PREFIXES` | 0 (em tempo de execução) | `include_twin` acrescenta `/api/v1/custom/twin/stream/` à lista do middleware global (como `/camera/stream` está nos padrões públicos): `EventSource` não manda cabeçalho, quem valida o token é a dependência da rota. Se o upstream renomear a lista: 401 (falha fechada). |
| `backend/app/services/bambu_mqtt.py` | `register_raw_message_handler` / `unregister_raw_message_handler` | 0 | API pública do upstream usada sem alteração (conferir a assinatura ao atualizar a base). |
| `backend/app/main.py` / `services/printer_manager.py` / `api/routes/library.py` | `running_print_archive`, `resolve_plate_id`, `printer_manager.get_client`, `to_absolute_path` | 0 | Funções do upstream chamadas (só leitura) para achar o 3MF do job. Conferir ao atualizar a base. |

Cartão da impressora: não tem vídeo (só a miniatura do job), então não recebeu a chave. O gancho do painel de movimento fica no cartão e usa as mutações existentes.

## 4. Web Push no PWA (`custom(webpush)`)

Notificações nativas no PWA (inclusive com o app fechado) como provedor de notificação `webpush`
("Web Push (PWA)"). Como funciona, passo a passo no celular e problemas comuns: `custom/docs/notificacoes-pwa.md`.

Notificações das personalizações: o "Salvar" do catálogo chama `notify()` ao baixar um arquivo novo
("Modelo salvo na biblioteca", abre `/files`) e quando o download falha (abre `/model-sources`). O gêmeo digital não gera
alertas próprios (é só visualização; os eventos da impressão já vêm do `notification_service` do upstream).

### Interruptor

- Backend: `BAMBUDDY_CUSTOM_WEBPUSH=0` desliga rotas e provedor (a tabela continua existindo).
- Frontend: `localStorage.setItem('custom.webPush', 'off')`; nos testes (vitest) a UI fica desligada e o tipo
  `webpush` some da lista do modal (a suíte do upstream confere a lista exata); testes nossos ligam com
  `setWebPushOverride(true)` / `vi.stubEnv('MODE', 'production')`.

### Código nosso

| Arquivo | O que é |
|---|---|
| `backend/app/custom/webpush/crypto.py` | RFC 8291 (`aes128gcm`) e VAPID RFC 8292 (JWT ES256) só com `cryptography` + `PyJWT` (já na imagem; nenhuma dependência nova) |
| `backend/app/custom/webpush/keys.py` | par VAPID em `<DATA_DIR>/custom/webpush/vapid.json` (600), gerado uma vez |
| `backend/app/custom/webpush/models.py` | tabela `custom_webpush_subscriptions` (criada pelo `create_all` do upstream; o modelo é importado pelo `install()`) |
| `backend/app/custom/webpush/sender.py` | payload, envio httpx, limpeza 404/410, allowlist de serviços de push |
| `backend/app/custom/webpush/provider.py` | `send_for_provider`/`send_test` (ganchos do notification_service), links por evento, `notify()` para outras personalizações |
| `backend/app/custom/webpush/routes.py` | `/api/v1/custom/webpush/*` e o mount `/custom` (static/custom, `no-cache`) |
| `backend/app/custom/api.py` | `install()` do fork: +3 linhas chamando `webpush.register` |
| `frontend/public/custom/sw-push.js`, `webpush-badge.png` | handlers `push`/`notificationclick` do SW e badge monocromático |
| `frontend/src/custom/webpush/` | `useWebPush`, cartão "Notificações neste aparelho", banner de convite, preset de eventos, flags, API |
| `frontend/src/custom/i18n/` | textos do fork (en, pt-BR) mesclados no i18n (evento `loaded`, sem editar locales do upstream) |
| `backend/tests/custom/test_webpush.py`, `frontend/src/custom/__tests__/webpush.test.tsx` | testes |

### Pontos de contato no upstream

| Arquivo | Âncora | +/− | O que / por quê |
|---|---|---|---|
| `backend/app/schemas/notification.py` | `NOTIFY = "notify"` (enum `ProviderType`) | +1 | aceita o tipo `webpush` |
| `backend/app/services/notification_service.py` | `_send_test_notification`: após `image_data = await asyncio.to_thread(_load_sample_notification_image) ...`; `_send_to_provider`: após `if not provider.attach_photo: image_data = None` | +4, +6 | desvia `webpush` para `backend.app.custom.webpush` antes do `try` com a cadeia de `elif` (horário silencioso e attach_photo já aplicados). 6 linhas porque o formatter quebra a chamada. |
| `frontend/public/sw.js` | 1ª linha `// Bambuddy Service Worker` | +1 | `try { importScripts('/custom/sw-push.js'); } catch (e) {...}`. Sem trocar nomes de cache: o importScripts não passa pelo fetch handler e `/custom/*` vai com `no-cache`. Mudar o `sw.js` faz os aparelhos atualizarem o SW na próxima abertura. |
| `frontend/src/main.tsx` | `import { i18nReady } from './i18n'` | +1 | `import './custom/i18n'` |
| `frontend/src/api/client.ts` | `export type ProviderType =` | +1/−1 | `\| 'webpush'` |
| `frontend/src/components/AddNotificationModal.tsx` | import de `MultiPrinterOnly`; `const PROVIDER_VALUES` | +2/−1 | `...webPushProviderValues()` no fim da lista (sem campos de configuração) |
| `frontend/src/pages/SettingsPage.tsx` | import de `MultiPrinterOnly`; `{/* Left Column: Providers */}` + `<div>` | +2 | `<WebPushDeviceCard />` no topo da coluna de provedores |
| `frontend/src/components/Layout.tsx` | `import { useTranslation }`; `{/* Pages load on first open (#3175)...` | +2 | `<WebPushPromptBanner />` (convite único, dispensável; também roteia o clique da notificação quando o SW não consegue navegar) |

Total do Web Push no upstream (`git diff --stat gabriel..custom-webpush` sem os diretórios nossos): 8 arquivos, +20/−2.

## 5. Prévia instantânea da câmera (`custom(camera)`)

A câmera abre na hora com a imagem do Frigate (~3 fps, baixa) e troca para o vídeo em alta quando ele chega (~8 s a
frio). Detalhes e medições: `custom/docs/camera-previa.md`.

- Interruptores: `BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL` (sem ela, 404 e nada aparece); `localStorage['custom.cameraPreview']`.
- Código nosso: `backend/app/custom/camera_preview.py` (rota + prefixo público em tempo de execução, como o twin),
  `backend/app/custom/api.py` (+5), `frontend/src/custom/camera/`, `frontend/src/custom/twin/CameraOrTwin.tsx` (monta a
  prévia), testes `backend/tests/custom/test_camera_preview.py` e `frontend/src/custom/__tests__/cameraPreview.test.tsx`.
- Upstream: **nenhuma linha nova** (usa os ganchos do twin em `CameraPage.tsx`/`EmbeddedCameraViewer.tsx`). Depende de
  o `<img>` do stream ter `src` com `/camera/stream` e do `PUBLIC_API_PREFIXES` em `main.py` (conferir ao atualizar).

## 6. Filamentos em lista no card da impressora (`custom(filaments)`)

No modo impressora única, a seção FILAMENTS do card (página Impressoras) vira uma lista vertical minimalista: some o
cabeçalho "FILAMENTS" (rótulo, botão de backup do AMS, linha e o olho do externo) e o cabeçalho de cada unidade
("AMS-A" + umidade/temperatura, "Externo"); cada slot vira uma linha `bolinha | material | K | barra de nível`, AMS 1-4
e depois o externo. As três primeiras colunas têm largura fixa, então a trilha da barra (= 100%) começa e termina no
mesmo x em toda linha. Slot ativo mantém o anel verde do upstream; vazio fica esmaecido com "Vazio". Screenshots
(390x844): `custom/docs/screenshots/filamentos/`.

**Nada de lógica reimplementada**: os tiles continuam sendo os do upstream (mesmos `FilamentHoverCard` /
`EmptySlotHoverCard`, ações carregar/descarregar/RFID/atribuir/configurar, cadeia de nível Spoolman → inventário →
AMS, pílulas P1/↓). Só o contêiner da seção ganha uma classe e uma folha de estilo nossa (injetada uma vez em
`<style id="custom-filament-list-style">`) reorganiza o DOM existente. Custo: os seletores dependem da estrutura da
seção do upstream; o teste `filamentList.test.tsx` renderiza a PrintersPage real e falha se algum seletor deixar de
achar o elemento esperado.

Se o spool externo estiver oculto (preferência do upstream #1782), o cabeçalho da seção continua visível, porque é nele
que fica o olho para mostrá-lo de novo.

### Interruptor

- Só age com `useSinglePrinter().single` (ver seção 1).
- `frontend/src/custom/flags.ts`: `FILAMENT_LIST = 'on'`; no navegador `localStorage.setItem('custom.filamentList', 'off')`.
  Nos testes o efetivo é `'off'`; testes nossos usam `setFilamentListOverride('on')`.

### Código nosso

| Arquivo | O que é |
|---|---|
| `frontend/src/custom/printer/filamentList.ts` | `useFilamentListClass(base, externalSpoolHidden)` (className do contêiner), `FILAMENT_LIST_SELECTORS`, CSS e larguras das colunas |
| `frontend/src/custom/__tests__/filamentList.test.tsx` | seletores vs DOM do upstream, ordem, colunas fixas/barra, ativo, vazio, toque → hover card/ação do upstream, cabeçalho mantido com externo oculto, flag/modo desligados |

### Pontos de contato no upstream

| Arquivo | Âncora | +/− | O que / por quê |
|---|---|---|---|
| `frontend/src/pages/PrintersPage.tsx` | import após `import { useSinglePrinter } from '../custom/useSinglePrinter';`; após o `useCallback` de `toggleExternalSpool` (`}, [printer.id]);`); `<div className="mt-3">` logo acima de `{/* Section Header */}` + `{t('printers.filaments')}` | +3/−1 | `const filamentListClass = useFilamentListClass('mt-3', externalSpoolHidden);` e `<div className={filamentListClass}>`. Fora do modo/flag devolve `'mt-3'` (DOM idêntico ao upstream). |

Estrutura do upstream da qual o CSS depende (conferir ao atualizar a base): contêiner com 2 filhos (cabeçalho, `flex
flex-wrap` com um cartão por unidade); cada cartão com o cabeçalho como 1º filho e os slots em `.grid`; o visual do
slot é o 1º filho de `[data-testid="filament-slot"]`/`[data-testid="empty-slot"]`, com os `div` na ordem bolinha,
material, `KValueLine` (opcional) e trilha da barra por último.

## Build e imagem

- `custom/build.sh [--no-docker]`: lê `custom/BASE_VERSION`, confere que o `CMD` do `Dockerfile` do upstream é o mesmo do
  `custom/Dockerfile` (com o módulo trocado; se o upstream mudar, o build para), roda `npm ci` só se `node_modules`
  faltar/estiver mais velho que o `package-lock.json`, compila com `vite build` em `custom/.build/static` (não em
  `../static`, que é versionado pelo upstream) sob `systemd-run ... MemoryMax=3G`, roda o `check-browser-baseline`, copia
  `backend/app/custom` (sem `__pycache__`) para `custom/.build/backend_custom` e faz `docker build -f custom/Dockerfile
  custom/.build` com as tags `bambuddy-gabriel:<base>-<sha>` e `bambuddy-gabriel:latest` (`-dirty` no sha se `frontend/`,
  `custom/` ou `backend/app/custom` tiverem mudança não commitada).
- `custom/Dockerfile`: `FROM ghcr.io/maziggy/bambuddy:<base>`, troca `/app/static` pelo frontend compilado, copia só
  `backend/app/custom/` e repete o `CMD` do upstream com `backend.app.custom.asgi:app` no lugar de
  `backend.app.main:app` (ENTRYPOINT do upstream mantido). Escolhido em vez de um gancho de 2 linhas em `main.py` porque
  não exige copiar nenhum arquivo do upstream para a imagem; o custo é o `CMD` duplicado, vigiado pelo `build.sh`.
  O contexto é `custom/.build/` porque o `.dockerignore` do upstream exclui `static/`.
- Deploy (não automatizado aqui): trocar a imagem no stack `23-bambuddy.yml` em compose-migration. Se o compose
  definir `command:` próprio, ele precisa apontar para `backend.app.custom.asgi:app` (hoje não define).

## 7. Celular enxuto (2026-11-15)

| Ponto de contato (upstream) | O que faz | Interruptor |
|---|---|---|
| `components/EmbeddedCameraViewer.tsx` (1 import + `useFitCameraWindow(...)`) | janela flutuante da câmera na proporção da imagem (sem faixas pretas) | `custom.fitCameraWindow=off` |
| `contexts/EmbeddedCameraContext.tsx` (`shownCameras` filtra `isInlineCamera`) | não abre a janela flutuante da impressora cuja câmera está embutida no card | — |
| `pages/PrintersPage.tsx` (`<InlineCamera>` antes de Temperatures) | modo impressora única: câmera/3D com os botões dentro do card (`custom/camera/InlineCamera.tsx`) | `custom.inlineCamera=off` |
| `pages/PrintersPage.tsx` (`<InHeader>` em volta do bloco de status; rótulo STATUS oculto) + `components/Layout.tsx` (`<HeaderSlot>` em volta do logo) | bloco de status do card vira o cabeçalho do celular no lugar do logo (`custom/layout/`) | `custom.headerStatus=off` |
| `components/Layout.tsx` (botão de bug report do cabeçalho compacto) | escondido | `custom.bugReportButton=on` traz de volta |
| `pages/InventoryPage.tsx` (2 classes) | estoque sem busca e sem linha de filtros (voltam se houver filtro ativo) | `custom.minimalInventory=off` |
| `pages/MaintenancePage.tsx` (`data-custom-maint-card`) | cards de manutenção em uma linha, ações à direita (`custom/maintenance/`) | `custom.compactMaintenance=off` |

### Catálogo no celular (2026-11-16)
- Busca: seletor de fonte + campo + botão de lupa; busca só ao tocar na lupa ou dar Enter (antes buscava sozinha ao digitar). Sem título de seção quando há uma fonte só, e sem a nota "Filtrado pelo MakerWorld".
- Perfis: miniatura própria do perfil (`metadata.cover`), fotos do perfil selecionado no começo da galeria (`metadata.pictures`), texto do autor do perfil quando selecionado (`metadata.summary_html`, higienizado) e números como ícone + número. Sem autor do perfil, sem selo "Designer" e sem a lista de impressoras.

## Câmera e 3D lado a lado (2026-11-16)

- `frontend/src/custom/twin/CameraOrTwin.tsx` deixa câmera e gêmeo digital montados juntos, lado a lado, sem a chave Câmera | 3D. Tocar numa delas amplia; voltar fica no canto superior esquerdo e a outra continua ao vivo como PiP no canto superior direito (tocar no PiP troca).
- `useTwinActive` passou a retornar `false`: o stream da câmera não é mais pausado quando o 3D está em destaque.
- `frontend/src/custom/camera/useCameraImageFit.ts` dá largura/altura explícitas à imagem antes do `rotate()`; o flex não a encolhe mais com a câmera deitada (90/270°), causa das barras pretas no stream em resolução cheia.
- Gêmeo: enquadramento frontal elevado fixo (`el=0.45`, `ty=120`, `zoom=0.72`), sem oscilação nem aproximação automática ao objeto; a impressora carregada fica mais cinza (cor clara × 0,38, exposição 0,82, ambiente 0,7, luz principal 2,4).

## Ícone do app (2026-11-16)

- Fonte: `custom/brand/icon.svg` (broto impresso em camadas sob o bico, desenho original). `custom/brand/render.sh` gera `custom/brand/png/`.
- `custom/build.sh` copia os PNGs por cima de `static/img/` com os nomes do upstream (manifest e `index.html` intocados).
- `frontend/public/custom/sw-push.js` apaga uma vez os ícones antigos do cache do service worker (`ICON_VERSION`); subir a versão ao trocar o ícone de novo.
- Desligar: remover a linha `cp ... custom/brand/png` do build.

## Inventário sem ações raras (2026-11-16)

- `frontend/src/pages/InventoryPage.tsx` (+3/−1): com `minimalInventory()` ligado, some o subtítulo e os botões Importar/Exportar CSV, Locais, Fornecedores, Imprimir etiquetas e Atribuir por QR; fica só "Adicionar Carretel". Religar: `localStorage['custom.minimalInventory']='off'`.

## Card compacto da impressora (2026-11-16)

- `frontend/src/custom/printer/compactCard.ts` (+ `compactCard.css`): interruptor `compactCard(single)` (só modo impressora única; `localStorage['custom.compactCard']='off'` desliga).
- `frontend/src/pages/PrintersPage.tsx` (~13 ganchos de 1 linha, todos com `compactCard(single)`, comentário `custom(compact-card)`): selos de conexão/HMS/IA/manutenção/firmware só com problema; diâmetro do bico no rótulo do tile Bico (no lugar do selo); ventiladores só imprimindo ou girando; sem título "Controles" e sem a luz duplicada; parada mostra mover + verificação de placa, imprimindo mostra velocidade + Pausar + Parar. Desde 2026-11-18: o selo da fila (`{/* Queue Count Badge */}`) sai da linha de selos e vira o `QueueChip` (`CardExtras.tsx`) logo após a verificação de placa (+1 linha depois do `</div>` que fecha o grupo da placa, antes de `{/* Print Speed */}`); o wrapper dos controles de movimento ganha `data-custom-jog` e o CSS transforma o popover em bloco que abre/fecha dentro do card, abaixo dos botões (sem fundo que fecha ao tocar fora); e, com câmera embutida, card e página ficam com 0,5 rem de margem e o cabeçalho vazio do card perde a margem de baixo (câmera + 3D maiores).
  Acima do limite de ~10 linhas: são pontos distintos do mesmo card, cada um uma condição de uma linha; juntar tudo exigiria copiar o card.
- `frontend/src/custom/camera/inlineCamera.css`: barra da câmera sem recarregar, diagnóstico, abrir em janela e botões desativados.

## Meu MakerWorld: curtidos e salvos no catálogo (2026-11-16)

- O que faz: o botão ♥ "Meu MakerWorld" na barra do catálogo abre a lista de modelos que o usuário curtiu ou salvou no MakerWorld, com abas **Curtidos** e **Salvos**. O estado fica na URL (`?mine=likes|saved`), então o voltar do celular fecha a lista.
- Backend: `backend/app/custom/models_catalog/mine.py` e a rota `GET /api/v1/custom/models/makerworld/mine/{likes|saved}`, em `router.py`.
  - Usa a credencial Bambu Cloud salva do próprio usuário (`get_stored_token`), contra `api.bambulab.com`:
    - `design-service/my/design/like`;
    - `design-service/favorites/designs/{uid}`, com o uid de `user-service/my/profile`.
  - Não passa pelo cache compartilhado do catálogo.
  - Sem login ou com a sessão expirada, responde 409 com uma mensagem, nunca 401.
- Frontend: `AuthorView` aceita `mine`/`onMine`. O `ModelCatalog` tem o botão e o parâmetro `mine`. Os textos estão em `i18n.ts`, e `catalogApi.mine` em `api.ts`.
- Nenhum arquivo do upstream foi alterado.
- Testes:
  - `backend/tests/custom/test_models_catalog_mine.py`;
  - o teste de contagem de rotas em `test_models_catalog_routes.py`, de 9 para 10;
  - em `modelCatalog.test.tsx`, o teste "Meu MakerWorld".

### Dados importados da Bambu Cloud (2026-11-16, uma vez, sem código no repo)

- **Histórico**: 32 impressões de `user-service/my/tasks`, de 2026-10-21 a 11-10.
  - Viraram `print_archives` sem 3MF (`file_path=''`). Usam `extra_data.imported_without_3mf`, e não o `no_3mf_available` do upstream, porque esse dispara o aviso de "Armazenar arquivos no SD" dos últimos 30 dias. Também levam `source=bambu_cloud_history` e `cloud_task_id` (repetido em `subtask_id`).
  - Cada uma tem a miniatura da nuvem, a `print_log_entries` correspondente (estatísticas) e uma linha em `spool_usage_history` por cor.
  - Nas 10 que falharam, o gasto é estimado pela fração do tempo decorrido.
  - Scripts em `/tmp/bbui/import_cloud.py`, `import_log.py` e `fix_failed.py`.
  - Backup prévio: `/app/data/bambuddy.db.bak-20261116-antes-import-nuvem`.
- **Carretéis**: pesados em 2026-11-16 (`weight_locked`). `last_scale_weight` é **inteiro** no schema: gravar com decimal dá 500 em `GET /inventory/spools`. Os carretéis 5 (laranja) e 6 (preto) foram criados a partir do histórico da nuvem.

## Origem MakerWorld abre no catálogo interno (`custom(archive-source)`, 2026-11-18)

- `frontend/src/components/ArchiveDetailModal.tsx`: import após `verdictSourceKey`; o `<a href={archive.makerworld_url} target="_blank">MakerWorld</a>` do campo "Origem" vira `<MakerworldSourceLink url=... />` (+2/−3).
- `frontend/src/custom/archives/SourceLink.tsx`: link de modelo do MakerWorld → `/model-sources?tab=catalog&model=<id>&msrc=makerworld` (mesmo detalhe interno do catálogo; "voltar" retorna ao arquivo). Outros links continuam externos. Teste: `custom/__tests__/archiveSourceLink.test.tsx`.

## Recuperação de telas que não carregam (`custom(chunk-recovery)`, 2026-11-18)

- `frontend/src/App.tsx`:
  - import após o `lazyPage`;
  - no `ErrorBoundary`, uma linha antes do "UI Crash": se o erro é de carregamento de arquivo, mostra `<ChunkErrorFallback />`;
  - o botão "Retry" passa a recarregar a página (+3/−1). O `React.lazy` guarda a promessa que falhou, então limpar o estado nunca recuperava.
- `frontend/src/custom/app/chunkRecovery.tsx`:
  - `isChunkLoadError`;
  - a tela "Atualizando o Bambuddy…", que usa o `recoverFromMissingChunk` do upstream e, se não der certo, mostra o botão "Recarregar";
  - listeners de `vite:preloadError` e `unhandledrejection` para os imports dinâmicos fora do `lazyPage`.
- Teste: `custom/__tests__/chunkRecovery.test.tsx`.

## Bico e velocidade no card (`custom(printer-prefs)`, 2026-11-18)

- Backend `backend/app/custom/printer_prefs/router.py`, registrado em `api.py`:
  - `GET /custom/printers/{id}/prefs`;
  - `PUT /custom/printers/{id}/speed?mode=1..5`: troca já se estiver imprimindo e sempre grava como padrão em `data/custom/printer_prefs.json`;
  - `POST /custom/printers/{id}/nozzle?diameter=0.2|0.4`: MQTT `set_accessories`; responde 409 durante a impressão.
  - Um vigia (iniciado pelo `StartApplierMiddleware` no lifespan, ou no 1º GET) aplica a velocidade padrão uma vez por impressão, a partir da camada 2.
- Frontend `custom/printer/PrinterPrefsChips.tsx`, com chips "⌀ 0.4 mm" e "Velocidade" na linha de controles do card compacto.
- `PrintersPage.tsx`:
  - import;
  - 1 linha depois do `QueueChip`;
  - o botão de velocidade do upstream fica só fora do modo compacto (`!compactCard(single)`).
- Textos em `custom/i18n` (`custom.prefs.*`). O CSS do card compacto mantém os quatro controles na mesma linha.
- Ultra-rápido usa `M220 S208` (25 mm³/s de referência sobre 12 mm³/s). O chip em impressão mostra `spd_mag` quando há telemetria, inclusive percentuais fora da lista. O gancho em `bambu_mqtt.py` preserva `spd_mag` em relatórios parciais sem mudança de modo.
- Testes: `backend/tests/custom/test_printer_prefs.py` e `custom/__tests__/printerPrefsChips.test.tsx`.

## Biblioteca organizada por modelo (`custom(library-org)`, 2026-11-18)

- Só código do fork: `backend/app/custom/library_org/` (`organizer.py` monta o plano, `service.py` aplica e `router.py` expõe), registrado em `api.py`. Nenhum arquivo do upstream foi tocado.
- API:
  - `GET /custom/library/organize`: mostra o plano, sem mudar nada;
  - `POST`: aplica o plano;
  - `PUT /auto?enabled=`: liga ou desliga a rodada automática, a cada 120 s.
- Regras: ver `custom/docs/biblioteca-organizacao.md`.
  - Só mexe em arquivos soltos (na raiz ou direto em "MakerWorld" ou "Printables"), e só muda `folder_id` e `filename`.
  - A pasta de cada modelo fica gravada em `data/custom/library_org.json`.
- Testes: `backend/tests/custom/test_library_org.py`.

## Miniaturas com a cor do filamento (`custom(thumb-color)`, 2026-11-18)

- `backend/app/custom/thumb_color.py`, instalado em `api.py`. Envolve `plate_thumbnail._render_model_thumbnails` e `_render_at_size`, que recebe a classe do polígono, para passar a cor. Troca o `stl_thumbnail.BAMBU_GREEN` por um cinza neutro. Nenhuma linha do upstream foi editada.
  - **Atenção em updates:** se o upstream renomear essas funções, as miniaturas voltam a ficar verdes, e o teste `test_thumb_color.py::test_install_troca_a_cor_do_renderizador` acusa.
- Cor usada:
  - em fatiado, o filamento com mais gramas (`slice_info.config`);
  - em projeto, o extrusor mais usado (`model_settings`) mapeado em `filament_colour`;
  - cores muito escuras sobem para `#4A4A4A`.
- O `conftest` dos testes do fork desinstala o patch, para não afetar os testes do upstream.
- (2026-11-18, 2ª rodada) Quando a recarga comum não resolve, `hardReload()` limpa o CacheStorage, desregistra o SW e recarrega. Isso cobre o caso de um arquivo de `/assets` guardado corrompido pelo SW, que usa cache-first, e quebrava sempre a mesma tela. A tela de falha agora mostra a mensagem do erro.
  - `backend/app/custom/asset_404.py`: um 404 em `/assets/*` sai com `Cache-Control: no-store`. O upstream manda `max-age=14400`, então o navegador e o Cloudflare guardavam o 404.
  - Teste: `test_asset_404.py`.

## Barras de temperatura no card (`custom(temp-bars)`, 2026-11-19)

- Pedido do Gabriel: bico e mesa com uma barrinha igual à de nível de filamento.
  - Escala: mesa 27 → 67 °C (mínimo era 20; 27 a pedido em 2026-11-19) e bico 25 → 250 °C = 0 → 100%, com clamp.
  - Opacidade 0,6 com a mesa < 30 °C ou o bico < 40 °C; cada barra decide pela própria temperatura.
  - Cor sólida da posição atual, de azul claro `#7cc4ff` a vermelho vivo `#ff1a1a`, interpolada em HSL pelo violeta/magenta. Em RGB linear o meio vira um lilás cinza que parece "desligado". Não usa gradiente até a ponta: numa barra de ~100 px no celular, a ponta fica pequena demais para ler.
  - Tracinho branco no alvo, quando o alvo for > 0. O número da temperatura do upstream continua igual.
  - Bico duplo (`nozzle_2`, "L / R") não ganha barra no bico.
  - Layout (2026-11-19, 2ª rodada): os blocos de Bico e Mesa viram duas linhas de largura inteira (ícone · rótulo · número · barra), como as barras de filamento. `tempRowAttr()` põe `data-temp-row` no bloco do upstream e `printer/tempBars.css` faz o resto; bico duplo continua em blocos. O bloco "Impressão · Nh" (horas totais, `PrintHoursTile`) foi removido.
- Interruptor: `TEMP_BARS` em `custom/flags.ts`, ligado. Desliga com `localStorage.setItem('custom.tempBars', 'off')`. Nos testes o efetivo é `off`.
- Código:
  - `frontend/src/custom/printer/tempBarScale.ts`: escala, opacidade e cor, funções puras;
  - `frontend/src/custom/printer/TempBar.tsx`: componente.
- `PrintersPage.tsx`, +5 linhas:
  - import abaixo de `useFilamentListClass` (`TempBar, tempRowAttr`);
  - `{...tempRowAttr('nozzle'|'bed', status.temperatures)}` nos dois blocos (logo após `title={statusControlTitle}`);
  - `<TempBar kind="nozzle" .../>` antes de `{statusControlMenu === 'nozzle-temp' && (`;
  - `<TempBar kind="bed" .../>` depois do `<p>` de `{Math.round(status.temperatures.bed || 0)}°C`.
- Testes: `custom/__tests__/tempBars.test.tsx`, que cobre escala/clamp, os limiares 29,9/30 e 39,9/40, as cores nos extremos e no meio, o card real com a flag ligada e desligada, e o bico duplo.

## Rolagem de modais no PWA

O componente compartilhado limita o overlay ao viewport visível quando o teclado abre,
isola sua rolagem e deixa margem para a navegação do Android. O modal de envio usa o
mesmo tratamento tanto no Gerenciador de Arquivos quanto na página Impressoras.
`localStorage.setItem('custom.scrollableModals', 'off')` desativa ao reabrir o modal.

| Arquivo | Âncora | Efeito |
|---|---|---|
| `frontend/src/pages/SettingsPage.tsx` | criar, editar e excluir usuário, alterar senha | Usa `ScrollableModalOverlay`. |
| `frontend/src/components/Layout.tsx` | alterar senha pelo menu da conta | Usa `ScrollableModalOverlay`. |
| `frontend/src/components/{CreateUserAdvancedAuthModal,FileUploadModal,PurgeArchivesModal,PurgeOldFilesModal,AddExternalLinkModal,VirtualPrinterAddDialog,ConfirmModal,ConfirmOutcomeDialog}.tsx` | overlay externo | Usa `ScrollableModalOverlay`, preservando eventos e z-index de cada janela. |
| `frontend/src/custom/dialogs/` | `ScrollableModalOverlay.tsx` e CSS | Contém a rolagem, acompanha a área visível e reserva a margem inferior. |

## Perfil leve da câmera RTSP externa

| Arquivo | Âncora | Efeito |
|---|---|---|
| `backend/app/services/external_camera.py` | `_stream_rtsp`, argumentos de entrada e saída | Usa o perfil opcional de vídeo ao vivo do fork. |
| `backend/app/custom/camera_rtsp.py` | `BAMBUDDY_CUSTOM_LIGHT_RTSP=1` | Sondagem curta para o go2rtc e MJPEG de até 1280 px e 8 fps. |

Ver [prévia e perfil leve](docs/camera-previa.md).

## Prévia colorida de 3MF sem fatiamento

- `backend/app/custom/model_preview/` gera miniatura e GLB leve do 3MF original em processo limitado, uma renderização por vez. Usa paleta e atribuição de filamentos Bambu/Orca, inclusive `paint_color`. Em triângulos com subdivisão de pintura, a prévia simplificada usa a cor dominante. O 3MF original fica intacto.
- `api/routes/archives.py` informa se há G-code também nos arquivos sem metadados de placa. Ganchos em `api/routes/library.py` (upload, extração e importação) e `services/archive.py` (após commit) enfileiram a miniatura quando não veio embutida. `services/plate_thumbnail.py` aceita a paleta no renderizador existente.
- As rotas de prévia têm as mesmas permissões da mídia de origem. O GLB é reutilizado pelo hash de conteúdo. `backend/app/custom/api.py` monta as rotas.
- `frontend/src/custom/modelPreview/` e ganchos em `ArchivesPage`, `ModelViewerModal`, `ModelViewer`, `FileUploadModal` e `useWebSocket`: prévia geométrica de arquivos sem G-code, carregamento do GLB, preservação de pacotes 3MF enviados como ZIP e atualização da miniatura depois do render.
- Ligado no servidor com `BAMBUDDY_CUSTOM_MODEL_PREVIEW=1`. Para desativar no navegador, use `localStorage.setItem('custom.modelPreview', 'off')` no navegador. Projetos com múltiplas placas mantêm a seleção de placas do visualizador original.

- A lista, os cartões e o menu de detalhes usam `archivePreviewTarget` em conjunto. Abrir uma prévia geométrica antiga também salva a miniatura ausente para aquele registro, incluindo cópias que compartilham o mesmo conteúdo.
- O render conecta vértices de coordenadas idênticas dentro de cada peça e cor antes de simplificar a malha. Assim as junções do 3MF permanecem fechadas na prévia, como nas seis peças do Family Figurine Split. O cache `model-previews-v2` gera novamente as prévias dos arquivos já enviados.
- Em `ModelViewer`, o gancho `useModelAppearance` em `custom/modelPreview/appearance.tsx` abre o visor em **Colorido** e oferece **Branco**. Arquivos com pintura usam as cores do carregador. Quando todos os materiais do visor são brancos, uma paleta de visualização aplica cores distintas às peças carregadas. A troca de modo afeta apenas os materiais exibidos e preserva a câmera e o zoom. Segue o interruptor `custom.modelPreview`.

## Fatiamentos junto ao modelo de origem

- `backend/app/api/routes/library.py` e `schemas/library.py` projetam no resultado da listagem o ID da origem salvo em `file_metadata.sliced_from_library_file_id`, quando a origem também está visível na resposta.
- `frontend/src/custom/libraryFamilies/` reaproveita o vínculo para organizar grade, lista e colunas com os fatiamentos sob a origem na mesma pasta. Busca ou filtros que ocultam a origem mantêm os resultados fatiados acessíveis. Os arquivos conservam suas ações, pastas e IDs.
- Ganchos em `FileManagerPage` nos mapas de renderização e nas listas ordenadas usadas pelo teclado. Desativar com `localStorage.setItem('custom.libraryFamilies', 'off')` e recarregar.
- `ArchivesPage` usa a própria chave de título traduzível; o português do fork apresenta essa área como **Impressos**, inclusive no menu.

## Histórico único em Impressos

- **Impressos** abre no **Histórico**. Cada execução vem do registro de impressão. Um trabalho encerrado na fila também aparece quando não há registro visível da mesma execução. A relação usa `queue_item_id` ou o identificador de cobrança da execução quando o vínculo antigo está ausente. Várias execuções do mesmo arquivo continuam independentes e abrem no detalhe da execução correspondente.
- `GET /api/v1/custom/print-history` consulta as duas fontes sem migração. Permissões de leitura, propriedade e impressoras seguem as regras de cada fonte. Busca, filtros, ordenação e paginação ocorrem sobre o resultado combinado. A data segue o encerramento do trabalho, com início e criação como alternativas.
- **Arquivos** em Impressos oferece grade, lista, importação, exportação e operações sobre o 3MF. **Calendário** abre os registros reais de impressão. A fila mantém os trabalhos ativos, lotes, linha do tempo e pipelines. O endereço `/queue?tab=history` redireciona para Impressos quando o perfil pode ler o histórico de impressão. Perfis com acesso exclusivo à fila mantêm a aba legada.
- O histórico oferece remoção individual. Excluir um registro de impressão altera as estatísticas desse registro. Se a solicitação de fila ainda existir, aparecerá com a indicação **Registro da fila** e terá sua própria ação de remoção. A ação de limpeza em massa fica fora do histórico combinado. O reenfileiramento e a reimpressão no detalhe utilizam os diálogos existentes.
- Teste local e reversão no navegador com `localStorage.setItem('custom.printHistory', 'off')` seguido de recarga. O valor `on` permite habilitar o fluxo nos testes de interface.

| Arquivo | Âncora | Efeito |
|---|---|---|
| `backend/app/custom/api.py` | `install` | Registra a consulta combinada. |
| `frontend/src/App.tsx` | rota `queue` | Mantém o atalho antigo com redirecionamento. |
| `frontend/src/pages/QueuePage.tsx` e `components/QueueStatsBar.tsx` | lista de abas, filtros e resumo | Retiram a aba, a consulta e os filtros de histórico da fila quando Impressos concentra a visualização. |
| `frontend/src/pages/ArchivesPage.tsx` | inicialização da vista, consulta e bloco do registro de impressão | Usa a consulta combinada e os componentes em `custom/printHistory/`. Os ganchos também ligam a navegação, removem as ações de arquivo da vista de histórico e reutilizam paginação, colunas e edição de registro. São mais de dez linhas ao todo para manter essas operações no componente existente. |
| `frontend/src/api/client.ts` | `getPrintLog`, `PrintLogEntry` | Reaproveita o cliente autenticado e os filtros do registro de impressão. |
| `frontend/src/hooks/useWebSocket.ts` | fim de impressão, atualizações do arquivo e falha da fila | Atualiza a consulta de histórico após eventos de impressão. |

## Fatiamento fixo na A1

- `BAMBUDDY_CUSTOM_A1_SLICING=1` fixa o modelo na Bambu Lab A1 e exige escolher 0,2 ou 0,4 mm toda vez que se fatia. O diâmetro da operação seleciona o perfil oficial e a compatibilidade de processo, filamento e pipelines.
- O servidor exige `a1_nozzle_diameter` antes de criar o trabalho e monta o perfil de máquina. Valida o resultado antes de gravá-lo e usa as configurações embutidas ou de recuperação somente quando o 3MF já identifica o mesmo modelo e bico. A escolha vale para o próximo fatiamento, inclusive na execução e nas novas tentativas de pipelines.
- A análise preliminar dos filamentos de projetos para outras impressoras lê os slots do projeto. O fatiamento efetivo aplica o perfil da A1. A opção é configurada no servidor para valer também para clientes com a interface antiga em cache.

| Arquivo | Âncora | Efeito |
|---|---|---|
| `backend/app/api/routes/library.py` e `archives.py` | rotas de fatiamento e `_run_slicer_with_fallback` | Exige o diâmetro nos endpoints e valida o alvo em `backend/app/custom/a1_slicing.py`. Impressos registra o bico encontrado no 3MF novo. |
| `backend/app/api/routes/slicer_presets.py`, `slicer_pipelines.py` e schemas correspondentes | listagens | Expõem os perfis de máquina permitidos por diâmetro. |
| `backend/app/api/routes/pipeline_runs.py` e `backend/app/schemas/{pipeline_run,slicer}.py` | criação, nova tentativa e requisição de fatiamento | Validam o valor explícito antes de enfileirar e repassam a escolha ao trabalho. |
| `backend/app/services/slice_preview.py` | entrada de `get_preview_filaments` | Usa os metadados de projetos para outras impressoras. |
| `frontend/src/components/SliceModal.tsx`, `RunWithPipelineModal.tsx`, `pages/PipelineRunsPage.tsx` e `api/client.ts` | estado do preset, envio e nova tentativa | Montam o seletor de bico em `custom/slicing/` e usam a escolha para habilitar a ação e selecionar os perfis compatíveis. `SliceModal` toca mais de dez linhas porque o perfil alimenta os efeitos de seleção, o corpo da requisição e o filtro de pipelines. |

## Câmera nativa no menu da impressora

No menu ⋮ do cartão da A1, **Câmera nativa** abre um modal somente sob demanda para quem tem acesso à câmera
e já tem a câmera externa habilitada. O stream usa o token e a autorização por impressora do Bambuddy.
A seleção vale só para esse modal. O detector da mesa e o stream padrão continuam usando a configuração existente.
O cabeçalho do modal oferece o controle manual da luz da câmara a usuários com `printers:control`, pela API existente.

| Gancho upstream | Âncora | Efeito |
|---|---|---|
| `frontend/src/pages/PrintersPage.tsx` | `printerActionsMenu` | Chama `useNativeCamera` e monta o item e o modal. |
| `backend/app/api/routes/camera.py` | `camera_stream` | `native=true` escolhe a câmera integrada pela rota de stream existente, com o mesmo token e broadcaster. |

Interruptores: `localStorage['custom.nativeCamera'] = 'off'` oculta o item.
`BAMBUDDY_CUSTOM_NATIVE_CAMERA=0` desativa a seleção da câmera nativa na API.
