# Plotter de caneta da Bambu Lab A1

A aba **Plotter** usa a sessão do Bambuddy. A vetorização preserva a linha central e mede a largura local.
O plano transforma essa largura em compressão do suporte. A A1 recebe deslocamentos XYZ, com Z variando
ao longo do traço. A curva é uma calibração indireta de pressão, em milímetros de compressão.

## Preparar e calibrar

1. Monte o adaptador conforme as instruções do [A1 Plotter Module](https://makerworld.com/pt/models/2433877-a1-plotter-module#profileId-2737084).
   Confira a folga do suporte, seu curso útil e a posição da ponta em relação ao bico. A origem da mesa fica no
   canto da frente à esquerda. X aumenta para a direita e Y para o fundo. A ponta deve ficar fora da placa
   enquanto o bico faz o home de Z na frente. Use apenas o conjunto calibrado e mantenha fita e presilhas fora do movimento.
2. Prenda a folha. Selecione A4 (210 × 297 mm) ou ajuste largura, altura, margem e espessura. Mova a folha sobre
   a vista da mesa ou informe X e Y do canto inferior esquerdo. A4 pode ultrapassar a borda da mesa de 256 mm.
   O tracejado delimita a interseção entre a folha, a margem, a mesa e o alcance da ponta.
3. Em **Calibração da caneta**, informe o deslocamento da ponta em relação ao bico e o limite físico medido
   do suporte. Confirme as condições em **Operação** antes de iniciar o ajuste de altura. Acompanhe o home
   na máquina. Com a caneta sobre o papel, desça aos poucos até o primeiro contato e salve. A espessura da
   folha entra na compensação se o bico fez o home sobre ela.
4. Use **Cruz de alinhamento** para conferir a posição de XY. A correção do offset é o offset atual mais
   a diferença entre o ponto medido e o ponto esperado em cada eixo.
5. Gere **Escala de pressão** e confira os valores antes do envio. As linhas vão da menor à maior compressão
   de cima para baixo, seguidas por uma cunha de compressão crescente. Meça as larguras e salve os pares
   compressão/largura no perfil. Repita após trocar de caneta, suporte ou papel com espessura diferente.

## Da imagem ao papel

1. Selecione PNG ou JPEG. Compare **Original**, **Vetor** e **Sobreposição**. Se houver sombra, experimente
   a compensação de iluminação e o limiar.
2. Escolha **Mover desenho** e arraste sobre a folha. Faça pinça na tela ou use a roda do mouse sobre o
   desenho para mudar a largura mantendo o centro e a proporção. Também é possível ajustar rotação, largura
   e centro nos campos em milímetros, ou usar **Ajustar à área útil**.
3. Gere o plano e confira a simulação, a área percorrida e os avisos de recorte ou largura. O controle de tempo
   percorre a simulação resultante da leitura do G-code. A cor indica compressão e as linhas tracejadas
   indicam deslocamento sem contato. Sem curva de pressão medida, o plano avisa que usará pressão constante.
4. Baixe o `.gcode.3mf` validado ou confirme a montagem no painel de operação e use **Iniciar plotagem**.
   Acompanhe o primeiro home e o início dos traços na impressora.

## Código e limites

- Motor e API em `backend/app/custom/plotter/`. Testes em `backend/tests/custom/plotter/`.
- Interface em `frontend/src/custom/plotter/`. Perfis, imagens e planos recentes ficam sob
  `<dados>/custom/plotter/`. O mesmo motor é usado pelo harness offline em `3d-printing/pen plotter/`.
- Requer A1 com controle LAN disponível para enviar ou ajustar Z. A geração e a prévia funcionam com a A1 cadastrada e offline.
- A superfície física, o comportamento da mola, o fluxo da tinta e a sequência de firmware precisam ser
  aferidos na A1 antes de reaproveitar uma curva de pressão. Os valores de exemplo servem para simulação.

## Chapa PEI compartilhada com o Twin

O contorno e as três aberturas visíveis na foto delimitam a mesma chapa no editor 2D e no Twin 3D.
A peça quadrada de 258 × 258 mm fica centrada na área de trabalho de 256 × 256 mm.
As duas abas avançam além da área de trabalho. A chapa usa a espessura de 0,8 mm do CAD do Twin,
com contorno, aberturas e marcações posicionados pela foto em vista superior.

## Câmera do prato

Em **Mesa da A1 → Rastrear prato pela câmera**, o Bambuddy sobrepõe a área útil estimada ao quadro da câmera externa. O perfil usa a calibração fisheye existente da Thingino, uma estimativa do plano da chapa e referências da borda e da marca central. A busca local pela linha escura da chapa refina a borda frontal do quadrado. Na vista retificada, a busca varia somente a posição da chapa no eixo Y. A câmera, o ângulo e o enquadramento precisam ser os mesmos usados na geração do perfil.

A rota de leitura usa a mesma URL interna da prévia da câmera e exige `printers:read` no escopo da impressora. O processamento acontece enquanto a prévia do prato está aberta. O perfil local fica em `<dados>/custom/plotter/vision/<printer_id>.json`; tirar esse arquivo desativa a função para essa impressora. O perfil contém pequenos recortes da câmera e fica fora do Git. A sobreposição é uma estimativa visual. A origem do Y da máquina e a precisão em milímetros dependem de uma varredura com posições conhecidas. A prévia não altera as coordenadas do papel nem o G-code.
