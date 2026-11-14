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
- "Mais novos" = `designCreateSince=1` (criados nas últimas 24 h); rótulo "Recentes · 24 h".
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
