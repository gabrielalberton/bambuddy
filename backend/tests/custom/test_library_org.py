"""custom(library-org): plano de organização da biblioteca."""

from backend.app.custom.library_org.organizer import FileRow, FolderRow, build_plan, dedupe_names, sliced_name


def _folders():
    return {
        2: FolderRow(2, "MakerWorld", None, False, None, None),
        9: FolderRow(9, "Minha pasta", None, False, None, None),
    }


def _mw(fid, name, model, folder=2):
    return FileRow(fid, name, folder, "makerworld", f"https://makerworld.com/models/{model}#profileId-1", {}, False)


def _sliced(fid, name, src, folder=2, **meta):
    base = {
        "sliced_from_library_file_id": str(src),
        "sliced_for_model": "A1",
        "nozzle_diameter": "0.4",
        "layer_height": "0.2",
        "filament_type": "PLA",
        "print_time_seconds": "8175",
    }
    base.update(meta)
    return FileRow(fid, name, folder, "sliced", None, base, False)


def test_makerworld_vai_para_pasta_do_modelo_e_fatiado_junto_com_nome_descritivo():
    files = [_mw(62, "Burger press bambulab.3mf", 3369010), _sliced(65, "Burger press bambulab.gcode.3mf", 62)]
    plan = build_plan(files, _folders(), {}, title_of=lambda p: "Burger Press – 100 mm Patty Maker")
    moves = {m.file_id: m for m in plan.moves}
    assert moves[62].to_path == ["MakerWorld", "Burger Press – 100 mm Patty Maker"]
    assert moves[65].to_path == moves[62].to_path
    assert moves[65].new_filename == "Burger press bambulab - A1 0.4mm 0.20mm PLA 2h16m.gcode.3mf"


def test_nao_mexe_em_arquivo_na_pasta_do_dono_nem_renomeia_nome_escolhido():
    files = [_mw(1, "a.3mf", 5, folder=9), _sliced(2, "meu nome.gcode.3mf", 1, folder=9)]
    plan = build_plan(files, _folders(), {}, title_of=lambda p: None)
    assert plan.moves == []


def test_pasta_ja_criada_vale_mesmo_renomeada():
    folders = _folders() | {20: FolderRow(20, "Hamburguer", 9, False, None, None)}
    state = {"models": {"makerworld:7": {"name": "Velho", "folder_id": 20}}}
    plan = build_plan([_mw(1, "b.3mf", 7)], folders, state, title_of=lambda p: "X")
    assert plan.moves[0].to_path == ["Minha pasta", "Hamburguer"]


def test_familias_de_arquivos_proprios_e_avulsos():
    files = [
        FileRow(1, "Calib-fluxo3-rosa.stl", None, None, None, {}, False),
        FileRow(2, "Calib-fluxo3-rosa-frente-dir-pronto.gcode.3mf", None, None, None, {}, False),
        FileRow(3, "Avulso.gcode.3mf", None, None, None, {}, False),
    ]
    plan = build_plan(files, {}, {}, title_of=lambda p: None)
    paths = {m.file_id: m.to_path for m in plan.moves}
    assert paths[1] == paths[2] == ["Meus modelos", "Calib-fluxo3-rosa"]
    assert paths[3] == ["Meus modelos"]


def test_nomes_repetidos_ganham_numero():
    files = [_mw(1, "x.3mf", 5), _sliced(2, "x.gcode.3mf", 1), _sliced(3, "x.gcode.3mf", 1)]
    plan = build_plan(files, _folders(), {}, title_of=lambda p: "M")
    dedupe_names(plan, {})
    names = sorted(m.new_filename for m in plan.moves if m.new_filename)
    assert names == ["x - A1 0.4mm 0.20mm PLA 2h16m (2).gcode.3mf", "x - A1 0.4mm 0.20mm PLA 2h16m.gcode.3mf"]


def test_sliced_name_sem_metadados():
    assert sliced_name("a.3mf", {}) == "a.gcode.3mf"
