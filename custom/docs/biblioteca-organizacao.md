# Organização da biblioteca (custom(library-org))

## Estrutura

```
MakerWorld/<título do modelo>/   original(is) do MakerWorld (um por perfil) + fatiados deles
Printables/<título do modelo>/   idem
Meus modelos/<família>/          arquivos próprios (STL/3MF gerados pelos agentes) + fatiados/prontos
Meus modelos/                    arquivos próprios avulsos (família de 1)
```

Os fatiados levam um nome que diz o que são: `<origem> - A1 0.4mm 0.20mm PLA 2h16m.gcode.3mf`. Só são
renomeados quando o nome é o genérico que o fatiador deu; um nome escolhido pelo dono fica como está.

## Garantias

- Não apaga nada e não mexe nos bytes do arquivo: muda só `folder_id` e o `filename` exibido.
- Arquivos em pastas criadas pelo dono, pastas externas, pastas de projeto ou de arquivo não são tocados.
- O dono pode renomear ou mover a pasta de um modelo: os próximos arquivos daquele modelo vão para ela
  (o id fica gravado em `data/custom/library_org.json`).
- Nomes repetidos na mesma pasta ganham " (2)", " (3)".

## Cópias e vários objetos numa bandeja

- **Cópias de STL ou vários STL numa bandeja:** "Combinar" do upstream (`POST /library/combine`). Gera um
  3MF novo, e o fatiador organiza a bandeja.
- **Cópias ou mistura de 3MF do MakerWorld (com cores e configurações):** ainda não existe. Ver a
  proposta no relatório de 2026-11-18.
