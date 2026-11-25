"""Motor do plotter de caneta: imagem -> traços com largura -> G-code da A1 validado.

Uso típico fora do servidor::

    from backend.app.custom.plotter import engine
    drawing = engine.vectorize_image(open("desenho.png", "rb").read())
    plot = engine.make_plot(drawing, placement, paper, pen)
    if plot.ok:
        open("plot.gcode.3mf", "wb").write(plot.package())
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import calibration, package
from .gcode import GcodeResult, build_gcode, z_levels
from .plan import Issue, PenPath, PlanError, PlanOptions, PlanPaths, build_paths, placement_corners
from .profile import (
    A1,
    DEFAULT_PEN_TYPE,
    MACHINES,
    MOUNTS,
    PAPER_PRESETS,
    PEN_TYPES,
    Machine,
    Mount,
    Paper,
    PenProfile,
    PenType,
    Placement,
    ProfileError,
    drawable_area,
    home_point,
    machine_for_model,
    mount_info,
    pen_reach,
    pen_type_info,
)
from .raster import ImageError
from .strokes import Drawing, Stroke
from .validate import Report, thin_sim, validate
from .vectorize import VectorizeOptions, render_preview, vectorize, vectorize_image

__all__ = [
    "A1",
    "DEFAULT_PEN_TYPE",
    "MACHINES",
    "MOUNTS",
    "PAPER_PRESETS",
    "PEN_TYPES",
    "Drawing",
    "GcodeResult",
    "ImageError",
    "Issue",
    "Machine",
    "Mount",
    "Paper",
    "PenPath",
    "PenProfile",
    "PenType",
    "Placement",
    "PlanError",
    "PlanOptions",
    "PlanPaths",
    "Plot",
    "ProfileError",
    "Report",
    "Stroke",
    "VectorizeOptions",
    "build_gcode",
    "build_paths",
    "calibration",
    "drawable_area",
    "home_point",
    "machine_for_model",
    "make_plot",
    "mount_info",
    "package",
    "pen_reach",
    "pen_type_info",
    "placement_corners",
    "plot_paths",
    "render_preview",
    "thin_sim",
    "validate",
    "vectorize",
    "vectorize_image",
    "z_levels",
]


@dataclass
class Plot:
    """Um plot pronto (ou recusado): G-code, relatório do validador e avisos do planejamento."""

    title: str
    gcode: str
    report: Report
    paths: list[PenPath]
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    thumbnail: object = None

    @property
    def ok(self) -> bool:
        return self.report.ok

    def package(self) -> bytes:
        if not self.ok:
            raise PlanError("plot recusado pelo validador")
        return package.build_3mf(self.gcode, self.title, self.report.stats.get("time_s", 0.0), self.thumbnail)


def plot_paths(
    paths: list[PenPath],
    pen: PenProfile,
    paper: Paper,
    machine: Machine = A1,
    title: str = "plot",
    issues: list[Issue] | None = None,
    stats: dict | None = None,
) -> Plot:
    """Caminhos prontos -> G-code -> validação. Erro do validador deixa ``ok`` falso (e não empacota)."""
    issues = list(issues or [])
    if pen.mount == "rigid":  # vale para desenho e para os padrões de calibração
        issues.insert(0, Issue("warning", "rigid_flatness", RIGID_FLATNESS))
    result = build_gcode(paths, pen, paper, machine, title)
    report = validate(result.text, machine, pen, paper)
    thumb = package.render_thumbnail(paths, pen, paper, machine)
    return Plot(title, result.text, report, paths, issues, {**(stats or {}), "gcode": result.stats}, thumb)


RIGID_FLATNESS = "Sem mola: a folha tem que estar plana e bem presa; 0,1 mm de ondulação já muda o traço."


def make_plot(
    drawing: Drawing,
    placement: Placement,
    paper: Paper,
    pen: PenProfile,
    machine: Machine = A1,
    options: PlanOptions | None = None,
    title: str = "plot",
) -> Plot:
    planned = build_paths(drawing, placement, paper, pen, machine, options)
    return plot_paths(planned.paths, pen, paper, machine, title, planned.issues, planned.stats)
