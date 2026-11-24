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
  1. o `<img>` MJPEG do upstream abre como sempre, com a prévia do Frigate por cima;
  2. o vídeo H.264 toca escondido atrás dele (`z-index: -1`, o quadro ganha `isolation: isolate`);
  3. com o primeiro quadro, o `src` do `<img>` vira um SVG transparente do tamanho do vídeo: o MJPEG para (o navegador
     fecha a conexão e o backend encerra o ffmpeg), a prévia some e o vídeo aparece no mesmo retângulo e com o mesmo
     `transform` do `<img>` (zoom, arrasto e rotação do upstream continuam funcionando sobre o `<img>` transparente);
  4. `useTwinActive` (gancho que o upstream já chama) devolve `useH264Active`: pausa a checagem de travamento, senão o
     `/camera/status` sem MJPEG faria o upstream reconectar;
  5. se o H.264 cair ou travar (8 s sem dados), o `<img>` volta ao MJPEG e o player tenta de novo em 2/5/15/30 s;
     4404 desiste até recarregar a página;
  6. em segundo plano (PWA minimizado) a conexão fecha e nada trafega; ao voltar reabre, com o último quadro como
     pôster.
  Latência: janela de 5 s no buffer e velocidade ajustada pelo atraso (~1 s), como o player do go2rtc.
- **Upstream**: nenhuma linha nova. Depende de o `<img>` do stream ter `/camera/stream` no `src`, de o
  `useStreamImgRef` só repor o `src` quando a URL muda, da checagem de travamento respeitar `twinActive` e do CSP do SPA
  permitir `media-src blob:` e `connect-src ws: wss:`. Conferir ao atualizar.

Produção: `BAMBUDDY_CUSTOM_H264_WS_URL=ws://frigate-standalone:1984/api/ws?src=thingino_135` no `23-bambuddy.yml`.
O MJPEG (perfil leve) continua como reserva e nos primeiros segundos.

Desligar: tirar a variável (backend; tudo volta ao MJPEG) ou `localStorage['custom.h264'] = 'off'` (aparelho).

Capturas, verificação da mesa, prévia e gravações não mudam: seguem seus próprios caminhos.
