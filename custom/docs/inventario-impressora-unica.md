# Inventário: UI que só existe por haver várias impressoras (base v1.3.1, levantado em 2026-11-14)

Linhas referem-se à v1.3.1. Status por item fica em `custom/CUSTOMIZATIONS.md`.

## Base
- `api.getPrinters` (`frontend/src/api/client.ts:5399`, `GET /printers/`); 48 arquivos usam `useQuery({queryKey:['printers']})` (React Query deduplica). Não há hook central.
- Backend filtra a lista pelo acesso do usuário: "uma impressora" = uma visível para o usuário. Print modal (`PrintModal/index.tsx:893`) e K-profiles (`KProfilesView.tsx:960`) contam só `is_active`.
- Build: `vite.config.ts` `outDir: '../static'`; backend serve `static/` (`core/config.py:73`, `main.py:13219-13250`).
- Toggles existentes: nenhum `VITE_*`; settings via `hooks/useUiSettings.ts`; `localStorage` para preferências.

## Componentes compartilhados
1. `PrintModal/PrinterSelector.tsx` (218): chave "Impressora específica / Qualquer <modelo>" (397-445), modelo/local (448-531), lista de botões (565-694, alimenta `selectedPrinters`; o modal já autoseleciona a única ativa em `index.tsx:902-903`), dicas (697-726). Renderizado em `PrintModal/index.tsx:2253-2254`.
2. `BulkPrinterToolbar.tsx`: botão de seleção em massa em `PrintersPage.tsx:9964-9980`.
3. `CameraWall.tsx`: chave Cards/Cam Wall e link em `PrintersPage.tsx:9876-9923`; rota `/camwall`.
4. `CameraLauncher.tsx`: menu de câmeras (162-183), clique em 126; usado em `Layout.tsx:636` e `:769`.
5. `PrinterSearchPicker.tsx` (câmera externa) em `SettingsPage.tsx:4632`.
6. `QrAssignTargetModal.tsx` select 416-430 (já cai em `printers[0]`, 144).
7. `KProfilesView.tsx` select 1335-1349 (autoseleciona 938-946).
8. Filtro por impressora: `ProfilesPage.tsx:2572-2581` (estado 2308), `OrcaCloudProfilesView.tsx:182-191`.
9. `AddNotificationModal.tsx:727-742`; badge "Todas as impressoras" em `NotificationProviderCard.tsx:112-114`.
10. `AddSmartPlugModal.tsx:1515-1529` (vínculo real: padrão `printers[0]` para plugue novo, estado 96).
11. `HASensorModal.tsx:192-206` (padrão `printers[0]`, 32).
12. `WLEDSettings.tsx:225-239` (autoseleciona 95-98).
13. `StreamOverlayBuilder.tsx:380-399` (padrão 213).
14. `VirtualPrinterAddDialog.tsx:108-127` (estado 30), `VirtualPrinterCard.tsx:683-701`.
15. `SpoolmanSettings.tsx:512-526`.
16. `OctoEverywhereSettings.tsx:342-374`, `ObicoSettings.tsx:356-388`.
17. `SlicerPipelinesPanel.tsx` 204-232 e 460-477; `PipelineRunsPage.tsx:223-245`.
18. `EditArchiveModal.tsx:342-357` (campo real; manter).

## Páginas
- PrintersPage (9034): `StatusSummaryBar` (1244, render 10052); busca (10056-10082); `renderFilterControls` (9799-9837); `renderViewControls` (9839-9923, manter tamanho de card 9925-9958); seleção em massa (9964-9980); menu "Ligar" de plugues (9983-10031); agrupamento `groupedPrinters` (9721) e "selecionar todos" por grupo (10205-10217); rota `/printer-locations`.
- QueuePage: filtro impressora (2830-2845) e local (2861-2871); layout "Por impressora" (2899-2917, estado 1810); ordenar por impressora (1602, 3042); `BulkEditModal` select (410-429); rótulo de impressora por linha (857-871).
- ArchivesPage (3037): filtro (4348-4362) e do log (4663-4672); `localStorage['archiveFilterPrinter']` (3047); nome no card (1220) e linha (2589-2591); coluna do cabeçalho (4611, grid de 12); coluna `printer` do log (155, render 3462, `loadLogColumnConfig` 172).
- StatsPage: `SuccessRateWidget` (247-260); `TimeAccuracyWidget` (351-365); `PrinterStatsWidget` "Por impressora" (621-646).
- MaintenancePage: atribuir impressoras (719-741, estado 494); chips (920-962); cards de override (976-981); cabeçalho `PrinterSection` (333).
- InventoryPage: prefixo `printer_name` (330, 579).
- SystemInfoPage: listas informativas (414-420, 548-555).

## Settings
- "Impressora padrão" (`SettingsPage.tsx:1941-1962`); "expandir mapeamento por impressora" (6395-6416); aba "Acesso às impressoras" (6852, 7326) e `GroupEditPage.tsx:221-228`.

## SpoolBuddy (quiosque)
- `SpoolBuddyTopBar.tsx:61-77` (select central; autoseleciona 37-43); `SpoolBuddyLayout.tsx:184-192` (swipe; já inerte com <2); `AssignToAmsModal.tsx:538-560` (passo "1 escolher impressora", 121); `SpoolBuddyDashboard.tsx:598-620`; `SpoolBuddyQuickMenu` (47).
