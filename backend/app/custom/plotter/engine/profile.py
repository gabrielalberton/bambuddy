"""Máquina, caneta, papel e posição do desenho: os dados físicos do plotter, com validação.

Convenções (todas em mm, no sistema da mesa: X para a direita, Y para o fundo, origem no canto
frente-esquerda da placa):

- ``posição da ponta da caneta = posição do bico + (offset_x, offset_y)``;
- ``z_contact`` é o Z do BICO no instante em que a ponta encosta no papel;
- "aperto" (``depth``) é quanto o bico desce abaixo de ``z_contact``: mais aperto, traço mais largo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


class ProfileError(ValueError):
    """Dado físico inválido ou perigoso."""


@dataclass(frozen=True)
class Machine:
    key: str
    name: str
    plate_w: float
    plate_h: float
    # faixa em que o BICO pode andar durante o plot (dentro da placa; fora dela ficam a escova e o purgador)
    nozzle_x: tuple[float, float]
    nozzle_y: tuple[float, float]
    nozzle_z_max: float
    nozzle_z_min: float  # o bico nunca desce abaixo disto durante o plot, calibrado ou não
    home_y: float  # Y do bico no home do Z: borda da frente, a caneta (à frente do bico) fica fora da mesa


A1 = Machine(
    key="A1",
    name="Bambu Lab A1",
    plate_w=256.0,
    plate_h=256.0,
    nozzle_x=(0.0, 256.0),
    nozzle_y=(0.0, 254.0),
    nozzle_z_max=60.0,
    nozzle_z_min=0.6,
    home_y=3.0,
)

MACHINES = {"A1": A1}


def machine_for_model(model: str | None) -> Machine | None:
    """Só a A1: o adaptador (MakerWorld 2433877) é dela e a sequência de início foi escrita para ela."""
    norm = (model or "").upper().replace("BAMBU LAB", "").replace(" ", "").replace("-", "")
    return A1 if norm == "A1" else None


def _num(value, name: str, lo: float, hi: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"{name}: número inválido") from exc
    if out != out or out < lo or out > hi:
        raise ProfileError(f"{name}: fora da faixa {lo:g}..{hi:g}")
    return out


@dataclass
class PenProfile:
    name: str = "Caneta"
    offset_x: float = 0.0
    offset_y: float = -32.0
    z_contact: float | None = None  # None = altura de contato ainda não calibrada: não plota
    lift: float = 3.0  # quanto sobe acima do contato para deslocar sem riscar
    depth_min: float = 0.2  # aperto do traço mais fino (garante que a ponta encosta)
    depth_max: float = 1.2  # aperto do traço mais grosso
    max_compression: float = 3.0  # limite duro do suporte com mola
    line_width: float = 0.5  # largura nominal da ponta (pressão constante e pré-visualização)
    table: list[list[float]] = field(default_factory=list)  # [[aperto, largura], ...] medidos na folha de teste
    draw_speed: float = 25.0  # mm/s
    travel_speed: float = 100.0
    z_speed: float = 10.0
    dwell_ms: int = 0  # espera depois de baixar a caneta (tinta começar a sair)
    use_mesh: bool = True  # usa a malha de nivelamento salva (pressão mais uniforme na folha)

    @classmethod
    def from_dict(cls, data: dict | None) -> PenProfile:
        data = data or {}
        p = cls()
        p.name = str(data.get("name") or p.name)[:60]
        p.offset_x = _num(data.get("offset_x", p.offset_x), "offset_x", -80, 80)
        p.offset_y = _num(data.get("offset_y", p.offset_y), "offset_y", -80, 80)
        zc = data.get("z_contact", p.z_contact)
        p.z_contact = None if zc is None or zc == "" else _num(zc, "z_contact", 0.3, 40)
        p.lift = _num(data.get("lift", p.lift), "lift", 0.5, 20)
        p.depth_min = _num(data.get("depth_min", p.depth_min), "depth_min", 0.0, 6)
        p.depth_max = _num(data.get("depth_max", p.depth_max), "depth_max", 0.0, 6)
        p.max_compression = _num(data.get("max_compression", p.max_compression), "max_compression", 0.2, 8)
        p.line_width = _num(data.get("line_width", p.line_width), "line_width", 0.05, 10)
        p.draw_speed = _num(data.get("draw_speed", p.draw_speed), "draw_speed", 1, 150)
        p.travel_speed = _num(data.get("travel_speed", p.travel_speed), "travel_speed", 5, 300)
        p.z_speed = _num(data.get("z_speed", p.z_speed), "z_speed", 1, 25)
        p.dwell_ms = int(_num(data.get("dwell_ms", p.dwell_ms), "dwell_ms", 0, 2000))
        p.use_mesh = bool(data.get("use_mesh", p.use_mesh))
        if p.depth_max < p.depth_min:
            raise ProfileError("depth_max menor que depth_min")
        if p.depth_max > p.max_compression:
            raise ProfileError("depth_max maior que o aperto máximo do suporte (max_compression)")
        p.table = _clean_table(data.get("table") or [], p.max_compression)
        return p

    def to_dict(self) -> dict:
        return asdict(self)

    # -- calibração
    @property
    def contact_calibrated(self) -> bool:
        return self.z_contact is not None

    @property
    def pressure_calibrated(self) -> bool:
        return len(self.table) >= 2 and self.table[-1][1] > self.table[0][1]

    def width_range(self) -> tuple[float, float]:
        """Menor e maior largura que a caneta consegue fazer dentro de depth_min..depth_max."""
        if not self.pressure_calibrated:
            return (self.line_width, self.line_width)
        return (self.width_for_depth(self.depth_min), self.width_for_depth(self.depth_max))

    def width_for_depth(self, depth: float) -> float:
        if not self.pressure_calibrated:
            return self.line_width
        return _interp(depth, [r[0] for r in self.table], [r[1] for r in self.table])

    def depth_for_width(self, width: float) -> tuple[float, int]:
        """(aperto, -1 | 0 | +1): 0 = dentro da faixa, -1 = pediu mais fino, +1 = pediu mais grosso que dá."""
        if not self.pressure_calibrated:
            return (self.depth_min, 0)
        lo, hi = self.width_range()
        if width < lo - 1e-9:
            return (self.depth_min, -1 if width < lo * 0.85 else 0)
        if width > hi + 1e-9:
            return (self.depth_max, 1 if width > hi * 1.15 else 0)
        depths = [r[0] for r in self.table]
        widths = [r[1] for r in self.table]
        return (min(self.depth_max, max(self.depth_min, _interp(width, widths, depths))), 0)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            span = xs[i] - xs[i - 1]
            t = 0.0 if span <= 1e-12 else (x - xs[i - 1]) / span
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _clean_table(rows, max_depth: float) -> list[list[float]]:
    """Ordena por aperto e exige largura não decrescente (mais aperto nunca afina o traço)."""
    out: list[list[float]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ProfileError("tabela de pressão: cada linha é [aperto, largura]")
        depth = _num(row[0], "tabela: aperto", 0.0, max_depth)
        width = _num(row[1], "tabela: largura", 0.02, 20.0)
        out.append([round(depth, 3), round(width, 3)])
    out.sort()
    cleaned: list[list[float]] = []
    for depth, width in out:
        if cleaned and depth - cleaned[-1][0] < 1e-6:
            cleaned[-1][1] = max(cleaned[-1][1], width)
            continue
        if cleaned and width < cleaned[-1][1]:
            raise ProfileError("tabela de pressão: a largura tem que crescer junto com o aperto")
        cleaned.append([depth, width])
    if len(cleaned) > 24:
        raise ProfileError("tabela de pressão: no máximo 24 pontos")
    return cleaned


PAPER_PRESETS = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "Carta": (215.9, 279.4),
    "10x15": (100.0, 150.0),
}


@dataclass
class Paper:
    """Folha sobre a mesa: canto frente-esquerda (x, y) e tamanho (w, h), em mm da mesa."""

    x: float = 23.0
    y: float = 0.0
    w: float = 210.0
    h: float = 297.0
    margin: float = 5.0  # faixa da borda da folha em que não se desenha
    thickness: float = 0.1

    @classmethod
    def from_dict(cls, data: dict | None) -> Paper:
        data = data or {}
        p = cls()
        p.x = _num(data.get("x", p.x), "papel x", -400, 400)
        p.y = _num(data.get("y", p.y), "papel y", -400, 400)
        p.w = _num(data.get("w", p.w), "papel largura", 10, 600)
        p.h = _num(data.get("h", p.h), "papel altura", 10, 600)
        p.margin = _num(data.get("margin", p.margin), "papel margem", 0, 50)
        p.thickness = _num(data.get("thickness", p.thickness), "papel espessura", 0, 2)
        return p

    def to_dict(self) -> dict:
        return asdict(self)

    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class Placement:
    """Onde o desenho fica: centro (cx, cy) na mesa, largura física da imagem e rotação anti-horária."""

    cx: float = 128.0
    cy: float = 110.0
    width: float = 150.0  # mm que a LARGURA da imagem ocupa
    rotation: float = 0.0  # graus, anti-horário visto de cima

    @classmethod
    def from_dict(cls, data: dict | None) -> Placement:
        data = data or {}
        p = cls()
        p.cx = _num(data.get("cx", p.cx), "desenho cx", -500, 800)
        p.cy = _num(data.get("cy", p.cy), "desenho cy", -500, 800)
        p.width = _num(data.get("width", p.width), "desenho largura", 1, 1000)
        p.rotation = _num(data.get("rotation", p.rotation), "desenho rotação", -3600, 3600) % 360.0
        return p

    def to_dict(self) -> dict:
        return asdict(self)


def intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    out = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return out if out[2] > out[0] and out[3] > out[1] else None


def pen_reach(machine: Machine, pen: PenProfile) -> tuple[float, float, float, float]:
    """Retângulo que a PONTA DA CANETA alcança (faixa do bico deslocada pelo offset)."""
    return (
        machine.nozzle_x[0] + pen.offset_x,
        machine.nozzle_y[0] + pen.offset_y,
        machine.nozzle_x[1] + pen.offset_x,
        machine.nozzle_y[1] + pen.offset_y,
    )


def drawable_area(machine: Machine, pen: PenProfile, paper: Paper):
    """Onde dá para desenhar: papel (menos a margem) ∩ placa ∩ alcance da caneta. None se não sobra nada."""
    m = paper.margin
    inner = (paper.x + m, paper.y + m, paper.x + paper.w - m, paper.y + paper.h - m)
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return None
    area = intersect(inner, (0.0, 0.0, machine.plate_w, machine.plate_h))
    return intersect(area, pen_reach(machine, pen)) if area else None


def home_point(machine: Machine, paper: Paper) -> tuple[float, float, bool]:
    """(x, y, sobre_o_papel) do bico no home do Z.

    Fica na borda da frente (a caneta, à frente do bico, pendura fora da mesa e não risca nada). O X é
    escolhido numa faixa sem papel quando existe; se o papel cobre a borda toda o bico toca o papel e a
    referência sobe a espessura dele, o que o gerador compensa.
    """
    y = machine.home_y
    covered = paper.y <= y <= paper.y + paper.h
    left_free = max(0.0, min(paper.x, machine.plate_w))
    right_free = max(0.0, machine.plate_w - max(0.0, paper.x + paper.w))
    if not covered:
        return (machine.plate_w / 2.0, y, False)
    if left_free >= 12.0:
        return (max(6.0, left_free / 2.0), y, False)
    if right_free >= 12.0:
        return (machine.plate_w - max(6.0, right_free / 2.0), y, False)
    return (machine.plate_w / 2.0, y, True)
