# Verificação óptica do gêmeo da A1

O gêmeo pode animar o movimento assim que o usuário toca na seta. A indicação de sincronização precisa de outra fonte:
uma medida do cabeçote e da mesa com data de captura, convertida em milímetros e comparada com a pose exibida naquele
instante. Uma resposta MQTT ou HTTP de sucesso confirma o recebimento, e `home_flag & 7` indica o referenciamento
dos eixos. Nenhum desses eventos contém coordenadas.

## Comandos e observações da A1

- O código de [controle de eixos do Bambu Studio](https://github.com/bambulab/BambuStudio/blob/579712cca4cbc7b3520daedd043e9d827d7bffab/src/slic3r/GUI/DeviceCore/DevAxisCtrl.cpp)
  usa `back_to_center` nos modelos que anunciam homing MQTT e `G28` sem eixos para homing ocioso nos demais.
  O controle de movimento `xyz_ctrl` enviaria um eixo, uma direção e um modo. É um comando de movimento.
- Em 2026-11-22, a A1 em firmware 01.09.00.00 (controlador de movimento 00.01.30.75) aceitou via MQTT
  `M114`, `M114 R`, `M114 D` e `M400` seguido de `M114`. Apenas ecoou o comando e retornou
  `result: success`. A segunda sonda observou todos os envelopes MQTT recebidos na janela da consulta.
  Chegaram `gcode_line` e `push_status`, sem XYZ. Nenhuma movimentação foi enviada durante a investigação.
- O vídeo original de 640 × 360 do Frigate confirma a movimentação física no teste do usuário às 20:18–20:19.
  Entre dois quadros estáveis durante os movimentos de Z, a região do logo do cabeçote se deslocou 27 px na horizontal
  e 11 px na vertical, e a referência da mesa ficou no mesmo ponto. Depois do clique em Homing, o relógio do
  vídeo às 20:19:07 mostra a mesa deslocando, o de 20:19:13 mostra o cabeçote perto do meio e a rotina ainda
  movimenta o Z em quadros posteriores. Outros trechos do mesmo dia mostram o cabeçote saindo do enquadramento.
  O deslocamento em pixels é evidência de movimento. A escala depende da calibração e da posição no quadro.

## Conferência visual sem marcadores

No quadro 3D, o botão **Comparar com câmera** compara a pose exibida da A1 parada com dois quadros da
mesma câmera, separados por 1,2 s. Procura características próprias do equipamento, como o logo no
cabeçote, a borda da placa e a moldura da tela, sem depender de acessórios na máquina. A moldura fixa
permite recusar uma imagem se a câmera se deslocar. A posição no quadro é comparada com uma foto da mesma
A1 ao fim de um homing, de modo que a perspectiva do visualizador 3D pode continuar livre.

- **3D diferente da câmera** quando um lado está claramente próximo da referência de homing e o outro está
  longe. No replay do caso real, a foto depois do homing sinalizou divergência contra a antiga pose
  de espera (40, 170, 90 mm), e passou a conferência grosseira com a pose corrigida (128, 128, 5 mm).
- **Sem desvio visual grande** quando tanto o cabeçote quanto a placa estão próximos da referência e a pose
  visual do gêmeo também está. O método não mede XYZ físicos em milímetros.
- **Comparação inconclusiva** durante movimento, caso o quadro se repita, quando houver oclusão ou quando
  as duas poses estiverem longe da referência. A indicação é pontual e expira após alguns segundos.
  Dois quadros distintos ajudam a detectar um stream parado, mas não certificam o horário da câmera.
  A conferência não interfere nos movimentos, na pose do gêmeo nem na análise de impressão.

### Ativação e referência local

O botão aparece quando existe `<data>/custom/twin/visual/<printer_id>/profile.json` e
`BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL` está configurada para a câmera dessa impressora.
O perfil e suas imagens de referência ficam no volume privado. Para desligar, retire `profile.json`.
O endpoint usa o mesmo token e escopo de câmera das demais rotas do twin.

O perfil JSON fornece `size` (largura, altura), `reference_xyz_mm`, `twin_close_mm` e
`twin_far_mm` (limiares por eixo), `max_base_drift_px`, `max_template_disagreement_px` e `parts`.
Cada parte (`base`, `head`, `bed`) tem `center` e uma lista de `templates`. Cada template informa
`image` (arquivo relativo ao perfil), `box` e `region` (x, y, largura, altura), `min_score`,
`min_margin` e, opcionalmente, `scales`. Cabeçote e mesa têm também `close_px` e `far_px`.
As imagens podem variar com a iluminação, contanto que os templates de cada parte identifiquem
a mesma característica física. O perfil da A1 atual usa imagens em luz ambiente e infravermelho.

Para executar a comparação localmente sobre uma foto:

```bash
uv run --no-project --with opencv-python-headless python -m backend.app.custom.twin.visual_check \
  profile.json quadro.jpg --twin 128 128 5
```
