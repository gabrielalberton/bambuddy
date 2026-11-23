import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.app.api.routes.library import _run_slicer_with_fallback
from backend.app.custom.a1_slicing import fixed_a1_target
from backend.app.schemas.slicer import PresetRef, SliceRequest
from backend.app.services.printer_manager import printer_manager
from backend.app.services.slice_preview import get_preview_filaments
from backend.app.services.slicer_api import SlicerApiServerError, SlicerApiService, SliceResult


def _project(model: str, nozzle="0.4", *, gcode_models: tuple[str, ...] = ()) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps(
                {
                    "printer_model": model,
                    "printer_settings_id": f"{model} {nozzle} nozzle",
                    "nozzle_diameter": [nozzle],
                    "machine_start_gcode": "M1002 gcode_claim_action : 1",
                }
            ),
        )
        for plate, gcode_model in enumerate(gcode_models, 1):
            archive.writestr(
                f"Metadata/plate_{plate}.gcode",
                f"; printer_model = {gcode_model}\n; nozzle_diameter = {nozzle}\nG90\n",
            )
    return data.getvalue()


@pytest.fixture(autouse=True)
def lock_a1(monkeypatch):
    monkeypatch.setenv("BAMBUDDY_CUSTOM_A1_SLICING", "1")


@pytest.fixture
def old_client_request() -> SliceRequest:
    return SliceRequest(
        printer_preset=PresetRef(source="standard", id="Bambu Lab X1 Carbon 0.4 nozzle"),
        process_preset=PresetRef(source="standard", id="0.20mm Standard @BBL A1"),
        filament_preset=PresetRef(source="standard", id="Generic PLA @BBL A1"),
        export_3mf=True,
        use_embedded_settings=True,
    )


async def test_target_detects_a1_nozzle_without_using_a1_mini(db_session, printer_factory, monkeypatch):
    await printer_factory(model="A1 Mini")
    a1 = await printer_factory(model="N2S")
    reported_to = []

    def get_status(printer_id: int):
        reported_to.append(printer_id)
        return SimpleNamespace(nozzles=[SimpleNamespace(nozzle_diameter="0.20")])

    monkeypatch.setattr(printer_manager, "get_status", get_status)
    target = await fixed_a1_target(db_session)
    assert target is not None and target.preset.id == "Bambu Lab A1 0.2 nozzle"
    assert reported_to == [a1.id]


@pytest.mark.parametrize(
    ("model", "nozzle", "embedded"),
    [
        ("Bambu Lab X1 Carbon", "0.4", False),
        ("Bambu Lab A1 mini", "0.4", False),
        ("Bambu Lab A1", "0.2", False),
        ("Bambu Lab A1", "0.4", True),
    ],
)
async def test_slice_uses_a1_even_when_client_requests_x1c(
    db_session, monkeypatch, old_client_request, model, nozzle, embedded
):
    output = _project("Bambu Lab A1", gcode_models=("Bambu Lab A1",))
    with_profiles = AsyncMock(return_value=SliceResult(output, 10, 1, 2))
    from_project = AsyncMock(return_value=SliceResult(output, 10, 1, 2))
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", with_profiles)
    monkeypatch.setattr(SlicerApiService, "slice_without_profiles", from_project)
    source = _project(model, nozzle)

    result, used_embedded = await _run_slicer_with_fallback(
        db_session, model_bytes=source, model_filename="part.3mf", request=old_client_request
    )

    assert result.content == output
    assert used_embedded is embedded
    if embedded:
        from_project.assert_awaited_once()
        with_profiles.assert_not_awaited()
    else:
        from_project.assert_not_awaited()
        with_profiles.assert_awaited_once()
        assert (
            json.loads(with_profiles.call_args.kwargs["printer_profile_json"])["inherits"] == "Bambu Lab A1 0.4 nozzle"
        )
    assert old_client_request.printer_preset.id == "Bambu Lab X1 Carbon 0.4 nozzle"


async def test_x1c_never_becomes_the_fallback_after_a_sidecar_error(db_session, monkeypatch, old_client_request):
    monkeypatch.setattr(
        SlicerApiService, "slice_with_profiles", AsyncMock(side_effect=SlicerApiServerError("Bad result"))
    )
    fallback = AsyncMock()
    monkeypatch.setattr(SlicerApiService, "slice_without_profiles", fallback)

    with pytest.raises(HTTPException) as error:
        await _run_slicer_with_fallback(
            db_session,
            model_bytes=_project("Bambu Lab X1 Carbon"),
            model_filename="part.3mf",
            request=old_client_request,
        )

    assert error.value.status_code == 502
    fallback.assert_not_awaited()


async def test_output_with_an_x1c_plate_is_rejected_before_it_can_be_saved(db_session, monkeypatch, old_client_request):
    output = _project("Bambu Lab A1", gcode_models=("Bambu Lab A1", "Bambu Lab X1 Carbon"))
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", AsyncMock(return_value=SliceResult(output, 10, 1, 2)))

    with pytest.raises(HTTPException, match="não confirmou a Bambu Lab A1"):
        await _run_slicer_with_fallback(
            db_session,
            model_bytes=_project("Bambu Lab X1 Carbon"),
            model_filename="part.3mf",
            request=old_client_request,
        )


async def test_non_a1_filament_inspection_does_not_slice_with_the_source_profile(monkeypatch):
    preview = AsyncMock()
    monkeypatch.setattr(SlicerApiService, "slice_without_profiles", preview)
    result = await get_preview_filaments(
        kind="library_file",
        source_id=5,
        plate_id=1,
        file_bytes=_project("Bambu Lab X1 Carbon"),
        file_name="part.3mf",
        api_url="http://unused",
    )
    assert result is None
    preview.assert_not_awaited()
