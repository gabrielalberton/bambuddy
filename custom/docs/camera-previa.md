# Prévia instantânea da câmera

## Problema (medido em 2026-11-14)

| Caminho | Até a 1ª imagem |
|---|---|
| Stream do Bambuddy aberto do zero (RTSP 2304x1296 -> ffmpeg -> MJPEG) | 8,0-8,4 s |
| Stream baixo da Thingino (ch1, 640x360) | 6,9-8,0 s |
| `latest.jpg` do Frigate (640x360, ~3 fps) | 0,01-0,03 s |

A Thingino manda quadro-chave a cada 4 s (GOP 60 a 15 fps) e o ffmpeg só entrega o primeiro quadro depois de um
quadro-chave; o stream baixo tem o mesmo GOP, então não ajuda. Já o Frigate mantém a última imagem decodificada.

## Solução

- Backend: `backend/app/custom/camera_preview.py`, `GET /api/v1/custom/camera/stream/{id}/preview.jpg` (token de stream
  da câmera, como `/camera/stream`), repassa `BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL` (aceita `{printer_id}`). Sem a
  variável: 404. Só JPEG de até 2 MB, `no-store`.
- Frontend: `frontend/src/custom/camera/CameraPreview.tsx`, montado pelo `CameraOrTwin` (página da câmera e visualizador
  embutido). Acha o `<img>` do stream do upstream no quadro, mostra por cima a imagem do Frigate a cada 300 ms
  (selo "HD…") e some com fade de 250 ms quando o `<img>` tem o primeiro quadro (`naturalWidth > 0`). Some também se o
  stream der erro (o aviso do upstream fica visível) e não aparece em modo snapshot.
- Produção: `BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL=http://frigate-standalone:5000/api/thingino_135/latest.jpg` no
  `23-bambuddy.yml`.
- Desligar: tirar a variável (backend) ou `localStorage['custom.cameraPreview']='off'` (aparelho).

Complemento possível sem código: GOP 15 (1 s) no stream principal da Thingino reduz a espera da alta para ~1-2 s.

## Perfil leve de vídeo ao vivo

Com `BAMBUDDY_CUSTOM_LIGHT_RTSP=1`, o MJPEG ao vivo de uma câmera RTSP externa tem
largura máxima de 1280 px e até 8 fps. O FFmpeg descarta quadros antes de redimensionar
e codificar, e reduz a sondagem inicial para a fonte H.264 conhecida do go2rtc.
A opção é específica para essa implantação. Remover a variável volta aos parâmetros
do upstream. A prévia, as capturas individuais e a gravação do Frigate seguem seus
próprios caminhos.
