"""Esqueleto de 1 px -> traços (linha central + raio em cada ponto).

O esqueleto vira um grafo: pixels com 3+ vizinhos são junções (vizinhas entre si formam um único nó), o
resto são cadeias. Depois:

1. poda de rebarbas (ramo terminal que mal sai de dentro do traço de onde nasce);
2. fusão de nós ligados por uma ponte curta (um "X" costuma virar dois "Y" colados no esqueleto);
3. pareamento por boa continuidade em cada nó (quem segue reto é o mesmo traço; quem sobra termina ali);
4. montagem, cortando o miolo de cada junção, onde tanto o eixo quanto o raio saem distorcidos
   (no cruzamento o maior círculo inscrito é maior que qualquer um dos dois traços).

Coordenadas em px da imagem, com o centro do pixel (coluna j, linha i) em (j + 0,5, i + 0,5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

_OFFSETS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))


@dataclass
class TraceOptions:
    prune_ratio: float = 0.9  # ramo terminal precisa sair pelo menos isto × a própria largura
    prune_min_px: float = 2.0
    bridge_factor: float = 2.0  # ponte entre dois nós mais curta que isto × raio médio -> um nó só
    max_deviation_deg: float = 45.0  # desvio máximo para dois ramos serem o mesmo traço
    zone_factor: float = 1.2  # raio da zona distorcida em volta do nó, em raios do traço
    dot_ratio: float = 0.6  # traço mais curto que isto × a largura vira ponto


@dataclass
class RawStroke:
    pts: np.ndarray  # (n, 2) float32, x e y em px
    rad: np.ndarray  # (n,) float32, raio do traço (distância ao fundo) em px
    closed: bool = False

    @property
    def is_dot(self) -> bool:
        return len(self.pts) == 1


class _Node:
    __slots__ = ("x", "y", "r", "zone", "ends", "alive")

    def __init__(self, x: float, y: float, r: float, zone: float) -> None:
        self.x, self.y, self.r, self.zone = x, y, r, zone
        self.ends: set[tuple[int, int]] = set()
        self.alive = True


class _Edge:
    __slots__ = ("pts", "rad", "nodes", "alive", "closed")

    def __init__(self, pts: np.ndarray, rad: np.ndarray, n0: int, n1: int, closed: bool = False) -> None:
        self.pts, self.rad = pts, rad
        self.nodes = [n0, n1]
        self.alive = True
        self.closed = closed


def _path_len(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    d = np.diff(pts, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


class SkeletonGraph:
    def __init__(self, opts: TraceOptions | None = None) -> None:
        self.opts = opts or TraceOptions()
        self.nodes: list[_Node] = []
        self.edges: list[_Edge] = []
        self.dots: list[tuple[float, float, float]] = []

    # ------------------------------------------------------------------ construção
    @classmethod
    def build(cls, skel: np.ndarray, dt: np.ndarray, opts: TraceOptions | None = None) -> SkeletonGraph:
        g = cls(opts)
        ys, xs = np.nonzero(skel)
        n = int(ys.size)
        if n == 0:
            return g
        h, w = skel.shape
        idx = np.full((h + 2, w + 2), -1, dtype=np.int32)
        idx[ys + 1, xs + 1] = np.arange(n, dtype=np.int32)
        nb = np.stack([idx[ys + 1 + dy, xs + 1 + dx] for dy, dx in _OFFSETS], axis=1)
        del idx
        is_j = (nb >= 0).sum(axis=1) >= 3
        px = xs.astype(np.float32) + 0.5
        py = ys.astype(np.float32) + 0.5
        rad = dt[ys, xs].astype(np.float32)

        cluster = np.zeros(n, dtype=np.int32)
        if is_j.any():
            jmask = np.zeros((h, w), dtype=np.uint8)
            jmask[ys[is_j], xs[is_j]] = 1
            nlab, lab = cv2.connectedComponents(jmask, connectivity=8)
            cluster = lab[ys, xs].astype(np.int32)
            cj = cluster[is_j]
            cnt = np.bincount(cj, minlength=nlab).astype(np.float64)
            cnt[0] = 1.0
            cx = np.bincount(cj, weights=px[is_j], minlength=nlab) / cnt
            cy = np.bincount(cj, weights=py[is_j], minlength=nlab) / cnt
            cr = np.zeros(nlab, dtype=np.float64)
            np.maximum.at(cr, cj, rad[is_j])
            g.nodes.append(_Node(0.0, 0.0, 0.0, 0.0))  # índice 0 não é usado (rótulo 0 = fundo)
            g.nodes[0].alive = False
            for k in range(1, nlab):
                r = float(cr[k])
                g.nodes.append(_Node(float(cx[k]), float(cy[k]), r, g.opts.zone_factor * r + 1.0))

        # vizinhos de cadeia: tira quem é junção
        safe = np.maximum(nb, 0)
        chain_nb = np.where((nb >= 0) & ~is_j[safe], nb, -1)
        chain_deg = (chain_nb >= 0).sum(axis=1)
        nbl = nb.tolist()
        cnbl = chain_nb.tolist()
        isj = is_j.tolist()
        clus = cluster.tolist()
        visited = bytearray(n)

        def walk(start: int) -> list[int]:
            path = [start]
            visited[start] = 1
            cur = start
            while True:
                nxt = -1
                for j in cnbl[cur]:
                    if j >= 0 and not visited[j]:
                        nxt = j
                        break
                if nxt < 0:
                    return path
                visited[nxt] = 1
                path.append(nxt)
                cur = nxt

        def junctions_of(i: int) -> list[int]:
            return [clus[j] for j in nbl[i] if j >= 0 and isj[j]]

        chain_idx = np.nonzero(~is_j)[0]
        for start in chain_idx[chain_deg[chain_idx] <= 1].tolist():
            if visited[start]:
                continue
            path = walk(start)
            if len(path) == 1:
                jn = junctions_of(start)
                if len(jn) >= 2 and len(set(jn)) == 1:
                    continue  # pixel pendurado duas vezes no mesmo nó: não é traço
                a = jn[0] if jn else -1
                b = jn[1] if len(jn) >= 2 else -1
            else:
                ja, jb = junctions_of(path[0]), junctions_of(path[-1])
                a = ja[0] if ja else -1
                b = jb[0] if jb else -1
            g._add_edge(path, px, py, rad, a, b)
        for start in chain_idx.tolist():  # o que sobrou são laços fechados sem junção
            if visited[start]:
                continue
            path = walk(start)
            g._add_edge(path, px, py, rad, -1, -1, closed=len(path) >= 4)
        for node in g.nodes:  # nó sem cadeia nenhuma: borrão compacto
            if node.alive and not node.ends:
                node.alive = False
                g.dots.append((node.x, node.y, node.r))
        return g

    def _add_edge(self, path, px, py, rad, a: int, b: int, closed: bool = False) -> int:
        ids = np.asarray(path, dtype=np.int64)
        pts = np.stack([px[ids], py[ids]], axis=1)
        eid = len(self.edges)
        self.edges.append(_Edge(pts, rad[ids].copy(), a, b, closed))
        if a >= 0:
            self.nodes[a].ends.add((eid, 0))
        if b >= 0:
            self.nodes[b].ends.add((eid, 1))
        return eid

    # ------------------------------------------------------------------ medidas
    def _length(self, eid: int) -> float:
        e = self.edges[eid]
        total = _path_len(e.pts)
        for side in (0, 1):
            nid = e.nodes[side]
            if nid >= 0:
                p = e.pts[0] if side == 0 else e.pts[-1]
                node = self.nodes[nid]
                total += math.hypot(float(p[0]) - node.x, float(p[1]) - node.y)
        return total

    def _kill_edge(self, eid: int) -> None:
        e = self.edges[eid]
        e.alive = False
        for side in (0, 1):
            if e.nodes[side] >= 0:
                self.nodes[e.nodes[side]].ends.discard((eid, side))

    # ------------------------------------------------------------------ simplificação do grafo
    def simplify(self) -> None:
        self._dissolve()
        for _ in range(4):
            if not self._prune():
                break
            self._dissolve()
        if self._contract():
            self._dissolve()

    def _prune(self) -> bool:
        o = self.opts
        changed = False
        for node in self.nodes:
            if not node.alive:
                continue
            ends = list(node.ends)
            cands: list[tuple[float, int]] = []
            for eid, side in ends:
                e = self.edges[eid]
                if e.nodes[1 - side] != -1:
                    continue
                length = self._length(eid)
                r_free = float(e.rad[-1] if side == 0 else e.rad[0])
                # quanto o ramo realmente sai de dentro do traço onde nasce
                protrusion = length - node.r + r_free
                if protrusion < max(o.prune_min_px, o.prune_ratio * 2.0 * r_free):
                    cands.append((length, eid))
            if not cands:
                continue
            if len(cands) == len(ends):  # tudo em volta é ramo curto: fica com os dois maiores
                cands.sort()
                cands = cands[:-2]
            for _, eid in cands:
                self._kill_edge(eid)
                changed = True
        return changed

    def _dissolve(self) -> None:
        """Nó com 0, 1 ou 2 ramos deixa de ser junção."""
        for nid, node in enumerate(self.nodes):
            if not node.alive or len(node.ends) > 2:
                continue
            ends = sorted(node.ends)
            center = np.array([[node.x, node.y]], dtype=np.float32)
            if not ends:
                node.alive = False
                self.dots.append((node.x, node.y, node.r))
            elif len(ends) == 1:
                eid, side = ends[0]
                e = self.edges[eid]
                if side == 0:
                    e.pts = np.concatenate([center, e.pts])
                    e.rad = np.concatenate([e.rad[:1], e.rad])
                else:
                    e.pts = np.concatenate([e.pts, center])
                    e.rad = np.concatenate([e.rad, e.rad[-1:]])
                e.nodes[side] = -1
                node.ends.clear()
                node.alive = False
            elif ends[0][0] == ends[1][0]:  # laço preso só neste nó
                e = self.edges[ends[0][0]]
                e.pts = np.concatenate([e.pts, center])
                e.rad = np.concatenate([e.rad, [0.5 * (e.rad[0] + e.rad[-1])]]).astype(np.float32)
                e.nodes = [-1, -1]
                e.closed = True
                node.ends.clear()
                node.alive = False
            else:
                (e1, s1), (e2, s2) = ends
                a, b = self.edges[e1], self.edges[e2]
                p1, r1 = (a.pts, a.rad) if s1 == 1 else (a.pts[::-1], a.rad[::-1])  # termina no nó
                p2, r2 = (b.pts, b.rad) if s2 == 0 else (b.pts[::-1], b.rad[::-1])  # começa no nó
                mid = np.array([0.5 * (float(r1[-1]) + float(r2[0]))], dtype=np.float32)
                n0, n1 = a.nodes[1 - s1], b.nodes[1 - s2]
                a.alive = b.alive = False
                for old_e, old_s, other in ((e1, 1 - s1, n0), (e2, 1 - s2, n1)):
                    if other >= 0:
                        self.nodes[other].ends.discard((old_e, old_s))
                node.ends.clear()
                node.alive = False
                new = len(self.edges)
                self.edges.append(
                    _Edge(np.concatenate([p1, center, p2]), np.concatenate([r1, mid, r2]).astype(np.float32), n0, n1)
                )
                if n0 >= 0:
                    self.nodes[n0].ends.add((new, 0))
                if n1 >= 0:
                    self.nodes[n1].ends.add((new, 1))

    def _contract(self) -> bool:
        o = self.opts
        changed = False
        bridges = [
            (self._length(i), i)
            for i, e in enumerate(self.edges)
            if e.alive and e.nodes[0] >= 0 and e.nodes[1] >= 0 and e.nodes[0] != e.nodes[1]
        ]
        for _, eid in sorted(bridges):
            e = self.edges[eid]
            a, b = e.nodes
            if not e.alive or a < 0 or b < 0 or a == b:
                continue
            na, nb = self.nodes[a], self.nodes[b]
            length = self._length(eid)
            if length > o.bridge_factor * 0.5 * (na.r + nb.r):
                continue
            self._kill_edge(eid)
            for e2, s2 in list(nb.ends):
                self.edges[e2].nodes[s2] = a
                na.ends.add((e2, s2))
            nb.ends.clear()
            nb.alive = False
            na.x, na.y = 0.5 * (na.x + nb.x), 0.5 * (na.y + nb.y)
            na.r = max(na.r, nb.r)
            na.zone = max(na.zone, nb.zone) + 0.5 * length
            changed = True
        if changed:  # ponte paralela que virou laço minúsculo no nó fundido
            for i, e in enumerate(self.edges):
                if e.alive and e.nodes[0] >= 0 and e.nodes[0] == e.nodes[1]:
                    if self._length(i) < 2.0 * self.nodes[e.nodes[0]].zone:
                        self._kill_edge(i)
        return changed

    # ------------------------------------------------------------------ continuidade
    def _end_dir(self, eid: int, side: int, node: _Node) -> tuple[np.ndarray, float] | None:
        """Direção (saindo do nó) e raio do ramo, medidos fora da zona distorcida."""
        e = self.edges[eid]
        pts, rad = (e.pts, e.rad) if side == 0 else (e.pts[::-1], e.rad[::-1])
        d = np.hypot(pts[:, 0] - node.x, pts[:, 1] - node.y)
        outside = np.nonzero(d >= node.zone)[0]
        if outside.size:
            i0 = int(outside[0])
            far = np.nonzero(d[i0:] >= node.zone + max(5.0, 2.0 * node.r))[0]
            i1 = i0 + int(far[0]) if far.size else len(pts) - 1
            v = pts[i1] - pts[i0]
            norm = float(np.hypot(v[0], v[1]))
            if i1 > i0 and norm >= 3.0:
                return v / norm, float(np.median(rad[i0 : i1 + 1]))
        k = int(np.argmax(d))
        v = np.array([float(pts[k][0]) - node.x, float(pts[k][1]) - node.y], dtype=np.float32)
        norm = float(np.hypot(v[0], v[1]))
        if norm < 1e-3:
            return None
        return v / norm, float(np.median(rad))

    def _pair(self) -> dict[tuple[int, int], tuple[int, int]]:
        pair: dict[tuple[int, int], tuple[int, int]] = {}
        max_dev = self.opts.max_deviation_deg
        for node in self.nodes:
            if not node.alive or len(node.ends) < 2:
                continue
            ends = sorted(node.ends)
            info = [self._end_dir(eid, side, node) for eid, side in ends]
            cands: list[tuple[float, int, int]] = []
            for i in range(len(ends)):
                for j in range(i + 1, len(ends)):
                    if info[i] is None or info[j] is None:
                        continue
                    (di, ri), (dj, rj) = info[i], info[j]
                    cos = float(np.clip(-(di[0] * dj[0] + di[1] * dj[1]), -1.0, 1.0))
                    dev = math.degrees(math.acos(cos))
                    if dev > max_dev:
                        continue
                    cost = dev + 12.0 * abs(math.log2(max(ri, 0.5) / max(rj, 0.5)))
                    cands.append((cost, i, j))
            taken: set[int] = set()
            for _, i, j in sorted(cands):
                if i in taken or j in taken:
                    continue
                taken.update((i, j))
                pair[ends[i]] = ends[j]
                pair[ends[j]] = ends[i]
        return pair

    # ------------------------------------------------------------------ montagem
    def trace(self) -> list[RawStroke]:
        self.simplify()
        pair = self._pair()
        used: set[int] = set()
        out: list[RawStroke] = []

        def follow(eid: int, side_in: int) -> tuple[list[tuple[int, int]], bool]:
            seq: list[tuple[int, int]] = []
            first = (eid, side_in)
            while True:
                used.add(eid)
                seq.append((eid, side_in))
                nxt = pair.get((eid, 1 - side_in))
                if nxt is None:
                    return seq, False
                if nxt == first:
                    return seq, True
                if nxt[0] in used:  # não deveria acontecer; fecha por segurança
                    return seq, False
                eid, side_in = nxt

        for eid, e in enumerate(self.edges):
            if not e.alive or eid in used:
                continue
            if e.closed:
                used.add(eid)
                out.append(RawStroke(e.pts.astype(np.float32), e.rad.astype(np.float32), True))
                continue
            for side in (0, 1):
                if eid not in used and pair.get((eid, side)) is None:
                    seq, closed = follow(eid, side)
                    out.append(self._assemble(seq, closed))
        for eid, e in enumerate(self.edges):  # ciclos em que todo extremo tem par
            if e.alive and eid not in used:
                seq, _closed = follow(eid, 0)
                out.append(self._assemble(seq, True))
        for x, y, r in self.dots:
            out.append(RawStroke(np.array([[x, y]], np.float32), np.array([r], np.float32)))
        return [self._finish(s) for s in out if len(s.pts)]

    def _assemble(self, seq: list[tuple[int, int]], closed: bool) -> RawStroke:
        pts: list[np.ndarray] = []
        rads: list[np.ndarray] = []
        last = len(seq) - 1
        for k, (eid, side_in) in enumerate(seq):
            e = self.edges[eid]
            p, r = (e.pts, e.rad) if side_in == 0 else (e.pts[::-1], e.rad[::-1])
            n_in, n_out = e.nodes[side_in], e.nodes[1 - side_in]
            lo, hi = 0, len(p)
            if n_in >= 0:
                node = self.nodes[n_in]
                keep = np.nonzero(np.hypot(p[:, 0] - node.x, p[:, 1] - node.y) >= node.zone)[0]
                lo = int(keep[0]) if keep.size else len(p)
            if n_out >= 0:
                node = self.nodes[n_out]
                keep = np.nonzero(np.hypot(p[:, 0] - node.x, p[:, 1] - node.y) >= node.zone)[0]
                hi = int(keep[-1]) + 1 if keep.size else 0
            if lo >= hi:  # ramo inteiro dentro das zonas: fica o ponto do meio
                lo = len(p) // 2
                hi = lo + 1
            sp, sr = p[lo:hi], r[lo:hi]
            if k == 0 and not closed and n_in >= 0:
                node = self.nodes[n_in]
                pts.append(np.array([[node.x, node.y]], dtype=np.float32))
                rads.append(sr[:1])
            pts.append(sp)
            rads.append(sr)
            if k == last and not closed and n_out >= 0:
                node = self.nodes[n_out]
                pts.append(np.array([[node.x, node.y]], dtype=np.float32))
                rads.append(sr[-1:])
        return RawStroke(
            np.concatenate(pts).astype(np.float32), np.concatenate(rads).astype(np.float32), closed and len(seq) > 0
        )

    def _finish(self, s: RawStroke) -> RawStroke:
        """Traço mais curto que a própria largura vira ponto."""
        if len(s.pts) == 1:
            return s
        length = _path_len(s.pts)
        if s.closed:
            length += float(np.hypot(*(s.pts[0] - s.pts[-1])))
        rmax = float(s.rad.max())
        if length < self.opts.dot_ratio * 2.0 * rmax:
            k = int(np.argmax(s.rad))
            center = s.pts.mean(axis=0, keepdims=True).astype(np.float32)
            # o ponto cobre o comprimento que o tracinho tinha
            return RawStroke(center, np.array([float(s.rad[k]) + 0.5 * length], np.float32))
        return s


def trace_skeleton(skel: np.ndarray, dt: np.ndarray, opts: TraceOptions | None = None) -> list[RawStroke]:
    return SkeletonGraph.build(skel, dt, opts).trace()
