# Vídeo ao vivo em H.264 (go2rtc)

## Problema (medido em 2026-11-24)

O stream ao vivo do upstream é MJPEG: o ffmpeg do Bambuddy decodifica o H.264 da Thingino e recodifica cada quadro em
JPEG (`-q:v 5`). A câmera manda 2304x1296 a 10 fps em ~1,5 Mbps. Medido no próprio container:

| Perfil MJPEG | Banda até o navegador | CPU (1 núcleo) |
|---|---|---|
| 1280 px, 8 fps (perfil leve, `BAMBUDDY_CUSTOM_LIGHT_RTSP=1`) | 5,8 Mbps | 32% |
| 1280 px, 10 fps | 7,1 Mbps | 34% |
| 1920 px, 10 fps | 13,7 Mbps | 52% |
| 2304 px, 10 fps (sem limite) | 17,9 Mbps | 42% |

Resolução cheia em MJPEG custaria ~18 Mbps por celular, um risco no Wi-Fi 2,4 GHz da casa (canal já em 61-76% de
ocupação, ver o change-log de 2026-11-24) e ~8 GB/h no 4G.

## Solução

O go2rtc do Frigate já entrega o mesmo H.264 em MP4 fragmentado para Media Source Extensions (o protocolo do
`video-rtc.js` dele), sem recodificar: resolução cheia, 10 fps, ~1,5 Mbps.

- **Backend** `backend/app/custom/camera_h264.py`: WebSocket `/api/v1/custom/camera/h264/{id}/ws?token=...` com o
  mesmo token de stream da câmera do `/camera/stream` (revalidado a cada 5 min; o token vale 60 min). Repassa
  `BAMBUDDY_CUSTOM_H264_WS_URL` (aceita `{printer_id}`). Do navegador só passa a primeira mensagem `mse`, reescrita e com
  a lista de codecs validada; do go2rtc só passam binários e texto `mse`/`error`. No máximo 6 sessões. Fecha com 4401
  (token), 4404 (sem a variável), 4429 (sessões) ou 4502 (go2rtc caiu). WebSocket não passa pelos middlewares HTTP do
  upstream, então não precisa de prefixo público.
- **Frontend** `frontend/src/custom/camera/H264Live.tsx` + `h264.ts`, montado pelo `CameraOrTwin` junto da prévia
  (página da câmera, janela flutuante e câmera embutida no card):
  1. **abertura direta** (desde 2026-11-25): o `CameraOrTwin` marca seu contêiner com `data-custom-h264-scope`. O gancho
     `claimStreamImg` no `useStreamImgRef` do upstream não põe a URL do MJPEG num `<img>` de stream ali dentro: põe um
     SVG transparente com o tamanho do último vídeo (`localStorage['custom.h264Size']`, padrão 1920x1080) e guarda a
     URL para a volta. O MJPEG nem abre (nenhum ffmpeg no servidor). A prévia do Frigate fica por cima enquanto o
     `<img>` tem `data-custom-h264-wait`;
  2. o vídeo H.264 toca atrás do `<img>` (`z-index: -1`, o quadro ganha `isolation: isolate`), no mesmo retângulo e
     com o mesmo `transform` (zoom, arrasto e rotação do upstream continuam funcionando sobre o `<img>` transparente);
  3. com o primeiro quadro, sai o `data-custom-h264-wait` (a prévia some com fade) e o SVG fica com o tamanho real do
     vídeo. Sem abertura direta (interruptor desligado ou H.264 em falha), o `<img>` abre o MJPEG e a troca pelo SVG
     acontece só aqui;
  4. `useTwinActive` (gancho que o upstream já chama) devolve `useH264Active`: pausa a checagem de travamento enquanto o
     `<img>` está sem MJPEG, senão o `/camera/status` faria o upstream reconectar;
  5. se o H.264 cair, travar (8 s sem dados) ou não ter quadro (8 s na abertura direta, 15 s com MJPEG na tela), o
     `<img>` volta ao MJPEG. O player tenta de novo em 2/5/15/30 s e, até ter quadro de novo, o gancho deixa o MJPEG
     abrir. 4404, navegador sem os codecs ou sem MediaSource: desiste até recarregar a página. Reserva que nenhum
     `H264Live` assume em 3 s também volta ao MJPEG;
  6. em segundo plano (PWA minimizado) a conexão fecha e nada trafega; ao voltar reabre, com o último quadro como
     pôster.
  Latência: janela de 5 s no buffer e velocidade ajustada pelo atraso (~1 s), como o player do go2rtc.
- **Upstream**: um gancho de 2 linhas em `frontend/src/hooks/useStreamImgRef.ts` (`claimStreamImg`). Depende também de
  o `<img>` do stream ter `/camera/stream` no `src`, de os visualizadores só zerarem o `src` direto (`src = ''`) e
  abrirem o stream pelo `useStreamImgRef`, da checagem de travamento respeitar `twinActive` e do CSP do SPA permitir
  `media-src blob:` e `connect-src ws: wss:`. Conferir ao atualizar.

Produção: `BAMBUDDY_CUSTOM_H264_WS_URL=ws://frigate-standalone:1984/api/ws?src=thingino_135` no `23-bambuddy.yml`.
O MJPEG (perfil leve) continua como reserva e nos primeiros segundos.

**A URL RTSP da impressora precisa pedir só o vídeo**: `rtsp://frigate-standalone:8554/thingino_135?video` (campo
`external_camera_url`, ajustado em 2026-11-24 23:44). A Thingino tem uma segunda fonte no go2rtc
(`ffmpeg:thingino_135#audio=opus`). Um consumidor RTSP que pede todas as faixas (o ffmpeg do MJPEG sem `?video`) faz o
go2rtc abrir essa fonte de áudio. Quando isso coincide com a abertura do H.264, o primeiro quadro-chave chega quebrado
(`PIPELINE_ERROR_DECODE` no `<video>`). A sessão cai e o vídeo só aparece na tentativa seguinte, ~6 s depois.

Medido no Chrome headless, com o 3D desligado (ms desde a navegação):

| Cenário | 1ª tentativa falhou | H.264 no ar |
|---|---|---|
| MJPEG sem `?video` + H.264 (como estava) | 5 de 7 | ~6 s nas falhas |
| MJPEG com `?video` + H.264 (atual) | 0 de 7 | 1,75–2,3 s |
| H.264 sem MJPEG (bloqueado no teste) | 0 de 10 | 1,6–2,5 s |
| Só MJPEG, para comparar | — | 1º quadro em 6,0–6,6 s |

Com `?video`, abrir o MJPEG junto não atrasa o H.264, inclusive no celular. Lá a demora é a página: a câmera surge em
~3–4,5 s e o H.264 entra 0,6–0,8 s depois. O MJPEG aberto junto só gastava: um ffmpeg por ~6 s no servidor, sem
nenhum quadro enviado. Por isso, desde 2026-11-25, a abertura é direta e o MJPEG ficou só como reserva.

Desligar: tirar a variável (backend; tudo volta ao MJPEG) ou `localStorage['custom.h264'] = 'off'` (aparelho).
Só a abertura direta: `localStorage['custom.h264Direct'] = 'off'` (o MJPEG volta a abrir junto e o H.264 assume no 1º
quadro).

Capturas, verificação da mesa, prévia e gravações não mudam: seguem seus próprios caminhos.
