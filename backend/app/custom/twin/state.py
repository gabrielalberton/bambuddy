"""Estado normalizado da impressora e lista branca do que o navegador pode receber."""

from __future__ import annotations

import time
from typing import Any

# Chaves do relatório MQTT `print` que o navegador pode receber (nada de rede, SSID, access code, câmera...).
PUBLIC_KEYS = (
    "gcode_state",
    "mc_percent",
    "mc_remaining_time",
    "layer_num",
    "total_layer_num",
    "gcode_file",
    "subtask_name",
    "spd_lvl",
    "spd_mag",
    "stg_cur",
    "mc_print_stage",
    "mc_print_sub_stage",
    "mc_print_line_number",
    "print_type",
    "bed_temper",
    "bed_target_temper",
    "nozzle_temper",
    "nozzle_target_temper",
    "chamber_temper",
    "cooling_fan_speed",
    "big_fan1_speed",
    "big_fan2_speed",
    "heatbreak_fan_speed",
    "lights_report",
    "nozzle_diameter",
    "print_error",
    "home_flag",
    "ams_status",
    "stg",
)
# Gravação para ajuste posterior: tudo, menos o que identifica rede/conta/câmera ou é segredo.
RECORD_DROP = {
    "net",
    "ipcam",
    "upload",
    "ap_ssid",
    "ssid",
    "access_code",
    "sequence_id",
    "online",
    "upgrade_state",
    "cfg",
    "lifecycle",
}
AMS_TRAY_KEYS = ("id", "tray_color", "tray_type", "tray_sub_brands", "remain", "tray_info_idx")


def _num(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return v
    return v


def record_view(print_msg: dict) -> dict:
    """Mensagem do relatório sem campos de rede/conta/câmera, para o JSONL."""
    return {k: v for k, v in print_msg.items() if k not in RECORD_DROP}


def merge_ams(cur: dict, new: dict) -> dict:
    out = dict(cur)
    for k, v in new.items():
        if k == "ams" and isinstance(v, list):
            by_id = {u.get("id"): u for u in out.get("ams", [])}
            for unit in v:
                u = dict(by_id.get(unit.get("id"), {}))
                for kk, vv in unit.items():
                    if kk == "tray" and isinstance(vv, list):
                        tr = {t.get("id"): t for t in u.get("tray", [])}
                        for t in vv:
                            tr[t.get("id")] = {**tr.get(t.get("id"), {}), **t}
                        u["tray"] = list(tr.values())
                    else:
                        u[kk] = vv
                by_id[unit.get("id")] = u
            out["ams"] = list(by_id.values())
        else:
            out[k] = v
    return out


class PrinterState:
    """Funde relatórios parciais (a A1 manda deltas) e entrega a visão pública."""

    def __init__(self) -> None:
        self.raw: dict = {}
        self.ams_root: dict = {}
        self.last_msg = 0.0
        self.source = "none"  # mqtt | bambuddy | none
        self.pr_at: float | None = (
            None  # instante (servidor) da última MUDANÇA observada de mc_percent/mc_remaining_time
        )

    def update(self, p: dict, source: str) -> None:
        p = dict(p)
        ams = p.pop("ams", None)
        now = time.time()
        for k, v in p.items():
            if k in ("mc_percent", "mc_remaining_time") and k in self.raw and self.raw[k] != v:
                self.pr_at = now
            self.raw[k] = v
        if isinstance(ams, dict):
            self.ams_root = merge_ams(self.ams_root, ams)
        self.last_msg = time.time()
        self.source = source

    def public(self) -> dict:
        out: dict = {}
        for k in PUBLIC_KEYS:
            if k in self.raw:
                out[k] = (
                    _num(self.raw[k])
                    if k
                    not in (
                        "gcode_file",
                        "subtask_name",
                        "gcode_state",
                        "lights_report",
                        "nozzle_diameter",
                        "print_type",
                    )
                    else self.raw[k]
                )
        trays = []
        for unit in self.ams_root.get("ams", []):
            for t in unit.get("tray", []):
                trays.append({"ams": _num(unit.get("id")), **{k: t.get(k) for k in AMS_TRAY_KEYS if k in t}})
        out["ams"] = {
            "tray_now": _num(self.ams_root.get("tray_now", 255)),
            "tray_tar": _num(self.ams_root.get("tray_tar")),
            "trays": trays,
        }
        return out
