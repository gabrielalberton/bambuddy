import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.app.api.routes.library import _run_slicer_with_fallback
from backend.app.custom.a1_slicing import fixed_a1_presets, fixed_a1_target
from backend.app.schemas.slicer import PresetRef, SliceRequest
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
def slice_request() -> SliceRequest:
    return SliceRequest(
        printer_preset=PresetRef(source="standard", id="Bambu Lab X1 Carbon 0.4 nozzle"),
        process_preset=PresetRef(source="standard", id="0.20mm Standard @BBL A1"),
        filament_preset=PresetRef(source="standard", id="Generic PLA @BBL A1"),
        export_3mf=True,
        a1_nozzle_diameter="0.4",
        use_embedded_settings=True,
    )


def test_target_uses_the_two_official_a1_profiles():
    presets = fixed_a1_presets()
    assert presets == {
        "0.2": PresetRef(source="standard", id="Bambu Lab A1 0.2 nozzle"),
        "0.4": PresetRef(source="standard", id="Bambu Lab A1 0.4 nozzle"),
    }
    assert fixed_a1_target("0.2").preset == presets["0.2"]
    assert fixed_a1_target("0.4").preset == presets["0.4"]


def test_disabled_lock_does_not_require_a_nozzle(monkeypatch):
    monkeypatch.delenv("BAMBUDDY_CUSTOM_A1_SLICING")
    assert fixed_a1_presets() is None
    assert fixed_a1_target(None) is None


@pytest.mark.parametrize("diameter", [None, "0.6"])
async def test_requires_explicit_nozzle_even_with_an_a1_printer_preset(
    db_session, monkeypatch, slice_request, diameter
):
    slice_request.a1_nozzle_diameter = diameter
    slice_request.printer_preset = PresetRef(source="standard", id="Bambu Lab A1 0.4 nozzle")
    sidecar = AsyncMock()
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", sidecar)

    with pytest.raises(HTTPException, match="Escolha o bico") as error:
        await _run_slicer_with_fallback(
            db_session, model_bytes=b"unused", model_filename="part.stl", request=slice_request
        )

    assert error.value.status_code == 422
    sidecar.assert_not_awaited()


@pytest.mark.parametrize(
    ("model", "nozzle", "chosen", "embedded"),
    [
        ("Bambu Lab X1 Carbon", "0.4", "0.4", False),
        ("Bambu Lab X1 Carbon", "0.4", "0.2", False),
        ("Bambu Lab A1 mini", "0.4", "0.4", False),
        ("Bambu Lab A1", "0.2", "0.4", False),
        ("Bambu Lab A1", "0.4", "0.2", False),
        ("Bambu Lab A1", "0.2", "0.2", True),
        ("Bambu Lab A1", "0.4", "0.4", True),
    ],
)
async def test_slice_uses_a1_even_when_client_requests_x1c(
    db_session, monkeypatch, slice_request, model, nozzle, chosen, embedded
):
    slice_request.a1_nozzle_diameter = chosen
    output = _project("Bambu Lab A1", chosen, gcode_models=("Bambu Lab A1",))
    with_profiles = AsyncMock(return_value=SliceResult(output, 10, 1, 2))
    from_project = AsyncMock(return_value=SliceResult(output, 10, 1, 2))
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", with_profiles)
    monkeypatch.setattr(SlicerApiService, "slice_without_profiles", from_project)
    source = _project(model, nozzle)

    result, used_embedded = await _run_slicer_with_fallback(
        db_session, model_bytes=source, model_filename="part.3mf", request=slice_request
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
            json.loads(with_profiles.call_args.kwargs["printer_profile_json"])["inherits"]
            == f"Bambu Lab A1 {chosen} nozzle"
        )
    assert slice_request.printer_preset.id == "Bambu Lab X1 Carbon 0.4 nozzle"


async def test_x1c_never_becomes_the_fallback_after_a_sidecar_error(db_session, monkeypatch, slice_request):
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
            request=slice_request,
        )

    assert error.value.status_code == 502
    fallback.assert_not_awaited()


async def test_output_with_an_x1c_plate_is_rejected_before_it_can_be_saved(db_session, monkeypatch, slice_request):
    output = _project("Bambu Lab A1", gcode_models=("Bambu Lab A1", "Bambu Lab X1 Carbon"))
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", AsyncMock(return_value=SliceResult(output, 10, 1, 2)))

    with pytest.raises(HTTPException, match="não confirmou a Bambu Lab A1"):
        await _run_slicer_with_fallback(
            db_session,
            model_bytes=_project("Bambu Lab X1 Carbon"),
            model_filename="part.3mf",
            request=slice_request,
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


async def test_a1_result_with_the_wrong_nozzle_is_rejected(db_session, monkeypatch, slice_request):
    slice_request.a1_nozzle_diameter = "0.2"
    output = _project("Bambu Lab A1", "0.4", gcode_models=("Bambu Lab A1",))
    monkeypatch.setattr(SlicerApiService, "slice_with_profiles", AsyncMock(return_value=SliceResult(output, 10, 1, 2)))

    with pytest.raises(HTTPException, match="bico de 0.2 mm"):
        await _run_slicer_with_fallback(
            db_session, model_bytes=_project("Bambu Lab A1"), model_filename="part.3mf", request=slice_request
        )


async def test_old_clients_cannot_enqueue_slices_or_pipeline_runs(
    async_client, db_session, printer_factory, monkeypatch, tmp_path, slice_request
):
    from sqlalchemy import func, select

    from backend.app.core.config import settings
    from backend.app.models.archive import PrintArchive
    from backend.app.models.library import LibraryFile
    from backend.app.models.pipeline_run import PipelineJob, PipelineRun
    from backend.app.services.slice_dispatch import slice_dispatch

    monkeypatch.setattr(settings, "base_dir", tmp_path)
    (tmp_path / "part.3mf").write_bytes(_project("Bambu Lab X1 Carbon"))
    printer = await printer_factory(model="A1")
    source = LibraryFile(
        filename="part.3mf",
        file_type="3mf",
        file_size=1,
        file_hash="test",
        file_path="part.3mf",
        source_type="uploaded",
    )
    archive = PrintArchive(filename="part.3mf", file_path="part.3mf", file_size=1)
    db_session.add_all([source, archive])
    await db_session.commit()
    dispatcher = AsyncMock()
    monkeypatch.setattr(slice_dispatch, "enqueue", dispatcher)
    body = slice_request.model_dump(exclude={"a1_nozzle_diameter"})
    pipeline = await async_client.post(
        "/api/v1/slicer-pipelines/",
        json={
            "name": "Saved X1C pipeline",
            "printer_preset": body["printer_preset"],
            "process_preset": body["process_preset"],
            "filament_presets": body["filament_presets"],
            "target_kind": "specific_printer",
            "target_printer_id": printer.id,
        },
    )
    assert pipeline.status_code == 201, pipeline.text

    for path, payload in [
        (f"/library/files/{source.id}/slice", body),
        (f"/archives/{archive.id}/slice", body),
        (f"/slicer-pipelines/{pipeline.json()['id']}/run", {"source_library_file_id": source.id}),
    ]:
        result = await async_client.post("/api/v1" + path, json=payload)
        assert result.status_code == 422, result.text
        assert "Escolha o bico" in result.json()["detail"]

    dispatcher.assert_not_awaited()
    assert (await db_session.scalar(select(func.count(PipelineRun.id)))) == 0
    assert (await db_session.scalar(select(func.count(PipelineJob.id)))) == 0
