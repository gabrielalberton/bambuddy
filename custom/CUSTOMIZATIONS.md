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
| `pages/PrintersPage.tsx` | import; logo após `const { data: printers, isLoading } = useQuery({ queryKey: ['printers'] ...});` | +13/−4 | `const { single }` + um `useEffect` que, no modo único, zera em memória (sem gravar no `localStorage`) busca, filtro de status/local, "ocultar offline", ordenação (→ `name`, desliga agrupamento e "selecionar todos" por grupo) e força `pageView='cards'`. Isso garante que preferência salva nunca esconda a única impressora. Esconde: `<StatusSummaryBar>`, caixa de busca (`{/* Only show search bar ...*/}`), divisor + `renderFilterControls()` da barra expandida, `ToolbarMenu` de filtros da barra compacta, bloco ordenação + link `/printer-locations` + chave Cards/Cam Wall + link `/camwall` (`{!single && (<>` após `{/* Sort dropdown */}` … `</>)}` após o link camwall), botão de seleção em massa (`{/* Bulk select toggle */}`, então `BulkPrinterToolbar` nunca aparece). Mantém o seletor de tamanho de card. Menu "Ligar" (plugues) só aparece com "ocultar offline", que fica desligado. 13 linhas: acima da meta de ~10, porque são 7 elementos independentes no mesmo arquivo. |
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

## Build e imagem

- `custom/build.sh [--no-docker]`: lê `custom/BASE_VERSION`, roda `npm ci` só se `node_modules` faltar/estiver mais velho
  que o `package-lock.json`, compila com `vite build` em `custom/.build/static` (não em `../static`, que é versionado pelo
  upstream) sob `systemd-run ... MemoryMax=3G`, roda o `check-browser-baseline` (o mesmo passo do `npm run build`) e faz
  `docker build -f custom/Dockerfile custom/.build` com as tags `bambuddy-gabriel:<base>-<sha>` e `bambuddy-gabriel:latest`
  (`-dirty` no sha se `frontend/` ou `custom/` tiverem mudança não commitada).
- `custom/Dockerfile`: `FROM ghcr.io/maziggy/bambuddy:<base>`, apaga `/app/static` e copia o frontend compilado.
  O contexto é `custom/.build/` porque o `.dockerignore` do upstream exclui `static/`.
- Deploy (não automatizado aqui): trocar a imagem no stack `23-bambuddy.yml` em compose-migration.
