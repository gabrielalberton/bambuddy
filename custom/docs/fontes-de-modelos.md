# Fontes de modelos do catálogo

Levantamento e verificação feitos em 2026-11-14 a partir do NUC, com requisições anônimas e User-Agent honesto
(`Bambuddy-gabriel-fork/1.3 (+https://github.com/gabrielalberton/bambuddy; catalogo de modelos)`). Nenhum desafio
Cloudflare/CAPTCHA foi contornado: onde apareceu desafio, a fonte foi descartada ou usada só pela API pública.

Código: `backend/app/custom/models_catalog/` e `frontend/src/custom/models/`. Origem: port de
1337faye/bambuddy-model-search (AGPL-3.0, commit `1b3b65b59`), mesma licença.

## Resumo

| Fonte | API | Precisa de chave? | Busca | Detalhe | Salvar/Fatiar | Filtro A1 |
|---|---|---|---|---|---|---|
| MakerWorld | `api.bambulab.com/v1/search-service` (busca) + `design-service` (detalhe/categorias) | não para navegar; download usa o login Bambu Cloud já salvo no Bambuddy | sim | sim | sim (rota do upstream `/makerworld/import`) | **sim, no servidor** |
| Printables | `api.printables.com/graphql/` | não | sim | sim | sim (arquivos públicos) | **não aplicável**; opção "impressora do autor" |
| Thingiverse | `api.thingiverse.com` (REST oficial) | **sim**, App Token grátis | implementado, não testado ao vivo | idem | idem | não aplicável |
| Thangs | sem API pública; site e `/api/...` respondem desafio Cloudflare (403 "Just a moment") | — | não | — | — | — |
| Cults3D | GraphQL oficial com usuário + chave (401 sem auth); a API dá metadados, não download de arquivos | sim | não implementado | — | — | — |
| MyMiniFactory | API v2 oficial (401 sem chave); download exige OAuth do usuário | sim (chave + OAuth) | não implementado | — | — | — |
| Crealty Cloud / Nexprint | sem API pública documentada | — | não | — | — | — |

## MakerWorld

- `design-service/design/search` (o que o upstream descartou) devolve vazio para requisições de servidor. O catálogo
  usa `search-service/select/design2` (busca/populares/recentes/categorias) e `select/design/nav?navKey=Trending`.
- O site makerworld.com responde 403 com desafio Cloudflare, então o JS do site não foi lido. O parâmetro foi achado
  sondando nomes no `select/design2` e comparando o `total`:

| Consulta (`select/design2`) | sem filtro | `devModelNames=N2S` (A1) | `N1` (A1 mini) | `ZZZ` (inválido) |
|---|---|---|---|---|
| `keyword=benchy` | 3571 | 3192 | 3009 | 0 |
| `keyword=lamp` | 4739 | 4437 | 3404 | 0 |
| `keyword=vase` | 4335 | 3953 | 3455 | 0 |
| `keyword=gridfinity` (pela imagem, via `/api/v1/custom/models`) | 4027 | 3802 | 3087 | — |
| sem palavra, ordem padrão | 735 | 732 | 722 | 0 |

  `ZZZ` → 0 prova que é filtro real; `A1` (nome) também dá 0, o valor é o `devModelName`. Vários códigos vão
  separados por vírgula (OU). Conferência semântica: na busca `gridfinity`, o modelo 546537 sumiu com `N2S` e os
  perfis dele são só P1S/H2C (sem `N2S` em `compatibility` nem `otherCompatibility`); os incluídos (1685835, 1259420,
  989027) têm `N2S` no perfil principal ou em `otherCompatibility`. Ou seja: **"tem algum perfil compatível com A1"**.
- Como a maioria dos perfis do MakerWorld declara compatibilidade com quase todas as Bambu, o filtro corta ~6-10%
  dos resultados de busca, não metade.
- O feed `nav?navKey=Trending` **ignora** `devModelNames` (471 → 471 com `N2S` e com `ZZZ`). Com o filtro ligado,
  "Em alta" usa o ranking padrão do `design2` sem palavra (733 modelos com `N2S` no teste, mesmo feed de "quentes");
  com o filtro desligado usa o `nav` Trending (471). Os totais do ranking sem palavra oscilam alguns itens entre
  chamadas.
- "Mais novos" = `orderBy=newUploads` (ordenação real listada no `cfg2`; até 2026-11-19 era o filtro
  `designCreateSince=1`, "Recentes · 24 h", que agora é o filtro "Publicado" do filtro avançado).
- Detalhe: perfis ordenados `nativo` (perfil feito para A1) → `compatível` (A1 em `otherCompatibility`) → `sem info`
  (perfis da comunidade que só vêm em `/instances`, sem dados de compatibilidade) → `outra impressora`; o primeiro
  fatiável nativo/compatível vem pré-selecionado. Ex.: modelo 1685835 → 3 perfis "Feito para A1" primeiro.
- Imagens: o CDN aceita `?x-oss-process=image/resize,w_N/format,webp`; capa de 2,7 MB vira ~4 KB no card.
- Download: não há downloader novo; "Salvar" chama a função da rota `POST /makerworld/import` do upstream
  (permissões, pasta "MakerWorld", dedupe por perfil, credencial Bambu Cloud). **Download real não foi testado** nesta
  sessão (instância descartável sem login Bambu Cloud); é o mesmo caminho já usado pelo importador por URL.

## Printables

- GraphQL público, anônimo. Introspecção desligada; campos achados pelas mensagens de erro ("Did you mean ...").
- Não há dimensões/bounding box (`dimensions`, `size`, `boundingBox` etc. não existem em `PrintType`/`STLType`) nem
  perfil por impressora nos STL/3MF. Logo **não dá para filtrar "cabe na A1 (256³ mm)"**.
- Existe `print.printer` (impressora que o autor usou) e `searchPrints2(printerIds: [Int])`. Ids via
  `{ printers { id name } }`: Bambu Lab A1 = 711, A1 mini = 682, P1S = 652, X1C = 768 etc.
  Medição: `benchy` 3870 → **2** com `printerIds:[711]`; sem palavra (populares) → **127** no catálogo todo; `vase` → 6.
  É um dado raro e diz "o autor imprimiu numa A1", não "serve só na A1". Por isso o filtro padrão mostra
  "não se aplica ao Printables" e a opção "Só modelos que o autor imprimiu numa A1 (raro)" fica desligada.
- Detalhe: STL e 3MF são fatiáveis; gcode/bgcode/PDF só salvar. Gcodes com impressora declarada recebem
  `nativo`/`outra impressora`; STL/3MF ficam "sem info de impressora".
- Download: `getDownloadLink` (mutação pública) → `files.printables.com`, sem redirect, até 200 MB, validação de STL/3MF.
  Arquivos restritos falham com mensagem clara.
- Imagens: miniaturas `.../thumbs/cover/640x480/<ext>/<nome>.webp` (cards) e `inside/1280x960` (galeria); originais de
  1-7 MB viram dezenas de KB.

## Thingiverse (desligado até ter token)

- `GET https://api.thingiverse.com/search/benchy` sem token → 401 `NO_TOKEN_PROVIDED`.
- Implementado: `/search/{termo}?type=things&sort=...`, `/things/{id}`, `/things/{id}/files`, `/things/{id}/images`;
  download por `download_url` com `Authorization: Bearer`, um único redirect permitido só para `cdn.thingiverse.com`
  (sem repassar o token ao CDN). Sem conceito de impressora ou dimensões: filtro A1 "não se aplica".
- **Não verificado ao vivo** (sem token). Em especial a busca sem palavra (`/search/?...`) pode precisar de ajuste.
- Para ligar: criar um app em https://www.thingiverse.com/apps/create (conta Thingiverse/MakerBot), copiar o
  **App Token** e pôr no container `BAMBUDDY_CUSTOM_THINGIVERSE_API_KEY=<token>` (env do stack, fora do git); reiniciar.
  Respeitar os termos da API do Thingiverse (uso pessoal/não comercial, atribuição).

## Filtro avançado por fonte (2026-11-19)

Botão **Filtros** (modal; folha de baixo no celular) com tudo o que cada API filtra **na requisição**, medido ao vivo
mudando o `total` da mesma busca com e sem o parâmetro (valor inválido → 0 ou erro). Esquema servido por
`GET /api/v1/custom/models/<fonte>/filters` (cache 1 h); o `/browse` recebe `filters=<JSON>` e devolve **400** para id ou
valor fora do esquema; os filtros entram na chave de cache. Só aparece o que funcionou; o que o servidor ignora ficou
de fora (lista abaixo). Ordenações extras entram no seletor de ordem quando a fonte está selecionada.

### MakerWorld (`select/design2`; opções do `GET search-service/cfg2` oficial, fallback estático)

Medido com `keyword=box` (base 5621-5644):

| Filtro (UI) | Parâmetro | Tipo | Evidência |
|---|---|---|---|
| Tipo de modelo (Destaque, Exclusivo, **CyberBrick**, Maker's Supply, Customizável, Paramétrico) | `model_tag` | um valor (vírgula = E: `cb,featured` → 0) | cb 8, featured 199, param 2081, custom 2324, ms 2597; sem palavra `cb` → 626 |
| Publicado (24 h, 7, 30, 90 dias, 1 ano) | `designCreateSince` (dias) | período | 7 → 1602 |
| Com perfil de impressão | `isPrintable=true` | sim/não | 5225 |
| Tipo de bico (Padrão, Alto fluxo, TPU 285) | `volumeTypes` | vários (vírgula = OU) | High Flow 120; + TPU285 → 123 |
| Diâmetro do bico (0.2/0.4/0.6/0.8) | `nozzleDiameters` | vários (OU) | 0.2 → 1334; 0.6 → 1281; 0.2,0.6 → 1956 |
| Cores (só uma cor / só multicor) | `multiColor` | um valor | false 4780 / true 3765 |
| Tempo de impressão (faixa, opções do cfg2 em minutos) | `printDuration=MIN-MAX` (∞ = vazio) | faixa | 0-15 → 1493; o nome `print_duration` do cfg2 é ignorado (5641) |
| Licença (CC0, BY, …, Standard Digital File License) | `licenses` | vários (OU) | BY 2222; BY,CC0 → 2576 |
| Ordem: Em alta, Downloads, **Mais novos**, Relevância, Curtidas, Impulsos, Impressões, Coleções, Aleatório | `orderBy` = `hotScore`/`downloadCount`/`newUploads`/`score`/`likeCount`/`boosts`/`printCount`/`collectionCount`/`random` | — | todos mudam a ordem; `newUploads` sem palavra traz o modelo publicado minutos antes |

Fora de propósito: `devModelNames` (é a chave "Só para minha A1"), `total_weight`/`weight` (ignorados), `my_filament`
e `materialTypes` (0 sempre/precisa de login), `designType` (reduz, mas sem significado confirmado), `withStep`.
Com qualquer filtro, "Em alta" usa o `design2` (o feed `nav` Trending ignora filtros).

**CyberBrick fixo na barra**: chave **CyberBrick** fora do modal = `model_tag=cb` (na visão "Todas" leva para o
MakerWorld). Cada hit traz `cyberBrickNeeded`/`isFeaturedCyberBrick`; o card ganha o selo **CyberBrick**
(`card.cyberbrick`). Ao vivo: `box` + CyberBrick + perfil → 9 (9/9 com selo); sem palavra + A1 → 590 (24/24 com selo).

### Printables (`searchPrints2`; licenças e materiais por `{ licenses { id name abbreviation } materials { id name } }`)

Medido com `query:"esp32"` (base 4469):

| Filtro (UI) | Argumento | Tipo | Evidência |
|---|---|---|---|
| Publicado (24 h … 1 ano) | `publishedDateLimitDays: Int` | período | 30 → 195 |
| Com makes | `hasMake: true` | sim/não | 1133 |
| Destaque | `featured: true` | sim/não | 2 |
| Premiado em concurso | `competitionAwarded: true` | sim/não | 8 |
| Só gerados por IA | `aiGenerated: true` | sim/não (false não exclui) | 128 |
| G-code (com / sem) | `filesType: GCODE / NONE` | um valor (`SLA` fora: a busca é só `printType:print`) | 297 / 4172 |
| Diâmetro do bico (G-code do autor) | `nozzleDiameters: [Float]` | vários | [0.4] → 283 |
| Material declarado | `materialIds: [Int]` (string dá erro de tipo) | vários | [1] PLA → 178; PLA + makes → 70 |
| Preço (grátis, pagos, clube, todos) | `paid: PaidEnum` | um valor | 4363 / 63 / 7 / 4537 |
| Em promoção | `sale: true` | sim/não | 0 no teste (argumento válido) |
| Licença | `licenses: [ID]` | vários | [1] CC-BY → 856 |
| Ordem: Populares, Mais novos, Relevância, **Melhor avaliados**, **Mais makes** | `ordering` = `popular`/`latest`/`best_match`/`rating`/`makes_count` | — | mudam a ordem |

Categoria continua no seletor de categorias, agora com o caminho ("Hobby & Makers / Electronics"). Não existem:
tags, autor, coleção, nota mínima, customizável, multicor, tempo de impressão.

### Thingiverse (`/search/{termo}?type=things`, com User-Agent)

Medido com `esp32` (base 4863):

| Filtro (UI) | Parâmetro | Tipo | Evidência |
|---|---|---|---|
| Categoria (seletor de categorias) | `category_id` (subcategorias de `/categories/{slug}` → `children`; 73 no total) | um valor | 92 Electronics → 1681 |
| Publicado entre (1 ano / 30 / 7 dias atrás) | `posted_after` + `posted_before` (fim só com início) | faixa | now-30d → 90; now-365d…now-30d → 820 |
| Com makes | `has_makes=1` | sim/não | 515; + licença cc → 212 |
| Destaque | `is_featured=1` | sim/não | 86 |
| Customizável | `customizable=1` | sim/não | 50 |
| Só remixes | `is_derivative=1` | sim/não | 944 |
| Só em andamento (WIP) | `is_wip=1` | sim/não | 578 |
| Licença | `license` (cc, cc-sa, cc-nd, cc-nc, cc-nc-sa, cc-nc-nd, pd0, gpl, lgpl, bsd) | um valor | cc → 1763 |
| Ordem: Populares, Mais novos, Relevância, **Mais makes**, **Texto** | `sort` = `popular`/`newest`/`relevant`/`makes`/`text` | — | mudam a ordem (likes/downloads/collections são ignorados) |

Ignorados pelo servidor: `is_customizable`, `has_remixes`, `file_types`, `is_nsfw`, `has_files`.

## Segurança

- Busca e detalhe nunca usam a credencial do usuário; só metadado público entra no cache (2 min; categorias 1 h; 128
  entradas).
- Proxy de imagens (`/api/v1/custom/models/<fonte>/thumbnail`) é sem auth como o `/makerworld/thumbnail` do upstream
  (tag `<img>`), mas só HTTPS nos hosts de CDN de cada fonte, sem redirect, 10 MB, e confere os bytes mágicos
  (SVG/HTML recusados).
- Permissões: MakerWorld = `makerworld:view` / `makerworld:import`; Printables/Thingiverse = leitura da biblioteca para
  navegar e `library:upload` para salvar.
- Descrições externas passam por DOMPurify (sem imagens remotas, estilos, scripts).

## Notificações (para o futuro Web Push)

Nada do catálogo gera notificação hoje. Eventos que mereceriam:
- download/salvamento concluído ou falho (principalmente MakerWorld lento ou bloqueado por 418/CAPTCHA);
- fatiamento iniciado pelo catálogo concluído/falho (já é job do upstream; o push deveria vir do job);
- credencial Bambu Cloud expirada detectada ao salvar do MakerWorld;
- fonte bloqueando o IP (418/429) de forma persistente.

## Smoke ao vivo

```bash
.venv-custom/bin/python -m custom.scripts.smoke_models_catalog vase
```
