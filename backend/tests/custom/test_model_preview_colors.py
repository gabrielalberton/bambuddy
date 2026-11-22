from backend.app.custom.model_preview.render import paint_slot


def test_bambu_filament_codes():
    assert [paint_slot(code) for code in ("", "4", "8", "0C", "1C")] == [0, 1, 2, 3, 4]


def test_split_paint_picks_dominant_leaf_and_broken_data_is_unpainted():
    assert paint_slot("4482") == 1
    assert paint_slot("C") == 0
    assert paint_slot("GG") == 0
