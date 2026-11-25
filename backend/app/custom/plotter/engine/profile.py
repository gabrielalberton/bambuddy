"""Máquina, caneta, papel e posição do desenho: os dados físicos do plotter, com validação.

Convenções (todas em mm, no sistema da mesa: X para a direita, Y para o fundo, origem no canto
frente-esquerda da placa):

- ``posição da ponta da caneta = posição do bico + (offset_x, offset_y)``;
- ``z_contact`` é o Z do BICO no instante em que a ponta encosta no papel;
- "aperto" (``depth``) é quanto o bico desce abaixo de ``z_contact``: mais aperto, traço mais largo.

O suporte tem dois modos (``PenProfile.mount``), cada um com limites próprios (ver ``MOUNTS``):

- ``spring`` (com mola): a caneta desliza no tubo contra a mola. O aperto comprime a mola, a força cresce
  devagar com o Z e a mola absorve ondulação do papel e da mesa. Custa folga lateral, atrito/histerese
  e uma força mínima (pré-carga) que limita o traço mais leve;
- ``rigid`` (sem mola, caneta travada): o aperto é a deformação da própria ponta. Resposta imediata e XY
  preciso, ideal para ponta de pincel; mas a largura muda muito com décimos de mm, então a folha tem que
  estar plana e presa, a malha de nivelamento é obrigatória e o aperto máximo é bem menor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


class ProfileError(ValueError):
    """Dado físico inválido ou perigoso."""


@dataclass(frozen=True)
class Mount:
    """Como a caneta está presa no módulo e o que isso muda no plano."""

    key: str
    name: str
    depth_limit: float  # maior aperto aceito no perfil (mm abaixo do contato)
    compression_limit: float  # teto do "limite do suporte" (max_compression)
    max_slope: float  # variação máxima de aperto por mm de traço (o planejador suaviza acima disto)
    approach_speed: float | None  # mm/s nos últimos APPROACH_GAP mm antes do papel (None = descida direta)
    ladder: tuple[float, ...]  # apertos candidatos da folha de teste
    ladder_top: float  # a folha de teste vai pelo menos até aqui (se o limite do suporte deixar)
    jog_steps: tuple[float, ...]  # passos oferecidos no ajuste de altura
    needs_mesh: bool  # exige a malha de nivelamento salva
    defaults: dict  # valores iniciais de um perfil novo neste modo


APPROACH_GAP = 0.3  # mm acima do contato em que a descida passa para a velocidade de aproximação

MOUNTS: dict[str, Mount] = {
    "spring": Mount(
        key="spring",
        name="Com mola",
        depth_limit=6.0,
        compression_limit=8.0,
        max_slope=0.6,
        approach_speed=None,
        ladder=(0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0),
        ladder_top=1.5,
        jog_steps=(-1.0, -0.5, -0.1, 0.1, 0.5, 1.0),
        needs_mesh=False,
        defaults={
            "name": "Caneta com mola",
            "depth_min": 0.2,
            "depth_max": 1.2,
            "max_compression": 3.0,
            "z_speed": 10.0,
        },
    ),
    "rigid": Mount(
        key="rigid",
        name="Sem mola",
        depth_limit=2.0,
        compression_limit=2.0,
        max_slope=0.25,
        approach_speed=2.0,
        ladder=(0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0),
        ladder_top=0.4,
        jog_steps=(-1.0, -0.1, -0.02, 0.02, 0.1, 1.0),
        needs_mesh=True,
        defaults={
            "name": "Caneta sem mola",
            "depth_min": 0.05,
            "depth_max": 0.4,
            "max_compression": 0.6,
            "z_speed": 5.0,
        },
    ),
}


@dataclass(frozen=True)
class PenType:
    """Tipo de caneta: valores INICIAIS (estimativas, não medidas) de aperto, largura e velocidade.

    ``depth`` dá (depth_min, depth_max, max_compression) por modo do suporte, sempre dentro dos limites de
    ``MOUNTS``. A curva real de cada caneta sai dos testes de espessura.
    """

    key: str
    name: str
    about: str
    line_width: float
    draw_speed: float
    depth: dict  # modo -> (depth_min, depth_max, max_compression); ausente = valores do modo

    def values_for(self, mount: str) -> dict:
        out = dict(MOUNTS[mount].defaults)
        if mount in self.depth:
            out["depth_min"], out["depth_max"], out["max_compression"] = self.depth[mount]
        if self.key != GENERIC_PEN_TYPE:
            out["name"] = f"{self.name} {MOUNTS[mount].name.lower()}"
        out.update(line_width=self.line_width, draw_speed=self.draw_speed, dwell_ms=0)
        return out


DEFAULT_PEN_TYPE = "bic"
GENERIC_PEN_TYPE = "outra"

# Esferográfica precisa de força para a esfera girar ("require a substantial amount of downward pressure",
# wiki da Evil Mad Scientist); feltro marca leve e gasta com força; gel falha rápido demais ou em papel
# com textura; pincel é o que mais varia de largura. Ver "pen plotter/references/tipos-de-caneta.md".
PEN_TYPES: dict[str, PenType] = {
    "bic": PenType(
        "bic",
        "Caneta BIC",
        "Esferográfica (BIC Cristal). A esfera só gira com força; a largura quase não muda.",
        0.4,
        25.0,
        {"spring": (0.4, 1.5, 3.0), "rigid": (0.05, 0.2, 0.3)},
    ),
    "canetinha": PenType(
        "canetinha",
        "Canetinha",
        "Hidrográfica de ponta de feltro. Marca com pouca força; força demais achata a ponta.",
        1.0,
        30.0,
        {"spring": (0.1, 0.8, 2.0), "rigid": (0.03, 0.3, 0.5)},
    ),
    "fineliner": PenType(
        "fineliner",
        "Fineliner / nanquim",
        "Ponta fina (Pigma Micron, Stabilo point). Quase sem força e sem variar a largura.",
        0.3,
        20.0,
        {"spring": (0.1, 0.5, 1.5), "rigid": (0.02, 0.12, 0.2)},
    ),
    "gel": PenType(
        "gel",
        "Caneta gel",
        "Pouca força; pode falhar rápido demais ou em papel com textura.",
        0.5,
        18.0,
        {"spring": (0.2, 0.9, 2.5), "rigid": (0.03, 0.15, 0.25)},
    ),
    "pincel": PenType(
        "pincel",
        "Caneta pincel",
        "Pentel Pocket Brush, Tombow Fudenosuke: a largura muda muito com o aperto. Melhor sem mola.",
        1.0,
        15.0,
        {"spring": (0.1, 2.0, 4.0), "rigid": (0.05, 1.0, 1.5)},
    ),
    "marcador": PenType(
        "marcador",
        "Marcador",
        "Ponta grossa (pincel atômico, Posca). Posca precisa de pressão para a tinta sair.",
        2.0,
        25.0,
        {"spring": (0.2, 1.0, 3.0), "rigid": (0.05, 0.3, 0.5)},
    ),
    "outra": PenType("outra", "Outra caneta", "Valores genéricos do modo do suporte.", 0.5, 25.0, {}),
}


def pen_type_info(pen_type: PenType) -> dict:
    return {
        "key": pen_type.key,
        "name": pen_type.name,
        "about": pen_type.about,
        "defaults": {mount: pen_type.values_for(mount) for mount in MOUNTS},
    }


def mount_info(mount: Mount) -> dict:
    """O que a tela precisa saber de cada modo."""
    return {
        "key": mount.key,
        "name": mount.name,
        "depth_limit": mount.depth_limit,
        "compression_limit": mount.compression_limit,
        "jog_steps": list(mount.jog_steps),
        "needs_mesh": mount.needs_mesh,
        "approach_speed": mount.approach_speed,
        "defaults": dict(mount.defaults),
    }


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
    mount: str = "spring"  # "spring" (com mola) ou "rigid" (sem mola, caneta travada): ver MOUNTS
    # chave de PEN_TYPES. Perfil novo (for_mount, ajustes padrão, tela) nasce BIC; os valores numéricos desta
    # classe e um perfil gravado antes dos tipos existirem são os genéricos, por isso "outra" aqui
    pen_type: str = GENERIC_PEN_TYPE
    offset_x: float = 0.0
    offset_y: float = -32.0
    z_contact: float | None = None  # None = altura de contato ainda não calibrada: não plota
    lift: float = 3.0  # quanto sobe acima do contato para deslocar sem riscar
    depth_min: float = 0.2  # aperto do traço mais fino (garante que a ponta encosta)
    depth_max: float = 1.2  # aperto do traço mais grosso
    max_compression: float = 3.0  # limite duro: curso útil da mola, ou o quanto a ponta aguenta sem mola
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
        mount = data.get("mount") or "spring"
        if mount not in MOUNTS:
            raise ProfileError("mount: use 'spring' (com mola) ou 'rigid' (sem mola)")
        pen_type = data.get("pen_type") or GENERIC_PEN_TYPE
        if pen_type not in PEN_TYPES:
            raise ProfileError("pen_type: tipo de caneta desconhecido")
        p = cls.for_mount(mount, pen_type)
        spec = MOUNTS[mount]
        p.name = str(data.get("name") or p.name)[:60]
        p.offset_x = _num(data.get("offset_x", p.offset_x), "offset_x", -80, 80)
        p.offset_y = _num(data.get("offset_y", p.offset_y), "offset_y", -80, 80)
        zc = data.get("z_contact", p.z_contact)
        p.z_contact = None if zc is None or zc == "" else _num(zc, "z_contact", 0.3, 40)
        p.lift = _num(data.get("lift", p.lift), "lift", 0.5, 20)
        p.depth_min = _num(data.get("depth_min", p.depth_min), "depth_min", 0.0, spec.depth_limit)
        p.depth_max = _num(data.get("depth_max", p.depth_max), "depth_max", 0.0, spec.depth_limit)
        p.max_compression = _num(
            data.get("max_compression", p.max_compression), "max_compression", 0.05, spec.compression_limit
        )
        p.line_width = _num(data.get("line_width", p.line_width), "line_width", 0.05, 10)
        p.draw_speed = _num(data.get("draw_speed", p.draw_speed), "draw_speed", 1, 150)
        p.travel_speed = _num(data.get("travel_speed", p.travel_speed), "travel_speed", 5, 300)
        p.z_speed = _num(data.get("z_speed", p.z_speed), "z_speed", 1, 25)
        p.dwell_ms = int(_num(data.get("dwell_ms", p.dwell_ms), "dwell_ms", 0, 2000))
        # sem mola, 0,1 mm de desnível da mesa já é boa parte da faixa de aperto: a malha não é opcional
        p.use_mesh = True if spec.needs_mesh else bool(data.get("use_mesh", p.use_mesh))
        if p.depth_max < p.depth_min:
            raise ProfileError("depth_max menor que depth_min")
        if p.depth_max > p.max_compression:
            raise ProfileError("depth_max maior que o aperto máximo do suporte (max_compression)")
        p.table = _clean_table(data.get("table") or [], p.max_compression)
        return p

    @classmethod
    def for_mount(cls, mount: str, pen_type: str = DEFAULT_PEN_TYPE) -> PenProfile:
        """Perfil novo com os valores iniciais do modo e do tipo de caneta."""
        return cls(mount=mount, pen_type=pen_type, **PEN_TYPES[pen_type].values_for(mount))

    @property
    def mount_spec(self) -> Mount:
        return MOUNTS[self.mount]

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
