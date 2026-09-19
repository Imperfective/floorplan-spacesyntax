"""2단계 — 생성된 도면을 좌표로 변환하고 지표를 계산한다.

FloorPlan은 "셀 인덱스 -> 방 키" 배열 하나로 도면을 표현한다.
여기서 좌표(폴리곤·중심점·바운딩박스)와 평가 지표를 모두 뽑아낸다.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

from .env import EnvWeights
from .spec import BuildingSpec
from .terms import normalizers, raw_values, score_from_values


@dataclass
class FloorPlan:
    """한 장의 도면. assignment[i]는 셀 i를 차지한 방의 키(또는 None)."""

    spec_key: str
    name: str
    assignment: list[str | None]
    source: str = "unknown"  # 생성 방법: claude / procedural / ortools / dwave
    meta: dict = field(default_factory=dict)

    # --- 생성자 ---------------------------------------------------------
    @classmethod
    def from_rects(
        cls, spec: BuildingSpec, rects: list[dict], name: str, source: str
    ) -> "FloorPlan":
        """[{room, x, y, w, h}, ...] 형태의 사각형 목록에서 도면을 만든다.

        겹치면 나중 사각형이 이깁니다. 빈 셀은 None으로 남고 repair()가 메웁니다.
        """
        assignment: list[str | None] = [None] * spec.n_cells
        for rc in rects:
            key = rc["room"]
            if key not in spec.room_by_key:
                continue
            for dy in range(int(rc["h"])):
                for dx in range(int(rc["w"])):
                    x, y = int(rc["x"]) + dx, int(rc["y"]) + dy
                    if 0 <= x < spec.width and 0 <= y < spec.height:
                        assignment[spec.idx(x, y)] = key
        return cls(spec.key, name, assignment, source)

    @classmethod
    def from_vector(
        cls, spec: BuildingSpec, x: dict, name: str, source: str
    ) -> "FloorPlan":
        """QUBO 해 벡터 {(room, cell): 0/1} → 도면. 중복 셀은 첫 방이 이깁니다."""
        assignment: list[str | None] = [None] * spec.n_cells
        for (room, cell), val in x.items():
            if val and assignment[cell] is None:
                assignment[cell] = room
        return cls(spec.key, name, assignment, source)

    # --- 좌표 데이터화 ---------------------------------------------------
    def cells_of(self, room: str) -> list[int]:
        return [i for i, k in enumerate(self.assignment) if k == room]

    def grid(self, spec: BuildingSpec) -> list[list[str | None]]:
        return [
            [self.assignment[spec.idx(x, y)] for x in range(spec.width)]
            for y in range(spec.height)
        ]

    def to_vector(self, spec: BuildingSpec) -> dict:
        """QUBO 변수와 같은 키 체계의 이진 벡터."""
        x = {(r.key, c): 0 for r in spec.rooms for c in spec.cells}
        for c, k in enumerate(self.assignment):
            if k is not None:
                x[(k, c)] = 1
        return x

    def coordinates(self, spec: BuildingSpec) -> dict[str, dict]:
        """방마다 좌표 기반 데이터를 뽑는다 — 이것이 2단계의 산출물이다."""
        out = {}
        for room in spec.rooms:
            cells = self.cells_of(room.key)
            if not cells:
                out[room.key] = {
                    "name": room.name, "cells": [], "area": 0,
                    "target_area": room.area, "bbox": None, "centroid": None,
                    "components": 0, "perimeter_cells": 0, "wall_length": 0,
                }
                continue
            pts = [spec.xy(i) for i in cells]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            out[room.key] = {
                "name": room.name,
                "cells": sorted(cells),
                "coords": sorted(pts),
                "area": len(cells),
                "target_area": room.area,
                "bbox": (min(xs), min(ys), max(xs) + 1, max(ys) + 1),
                "centroid": (sum(xs) / len(xs) + 0.5, sum(ys) / len(ys) + 0.5),
                "components": self._components(spec, cells),
                "perimeter_cells": sum(1 for i in cells if spec.is_perimeter(i)),
                "wall_length": self._wall_length(spec, set(cells)),
            }
        return out

    @staticmethod
    def _components(spec: BuildingSpec, cells: list[int]) -> int:
        """방이 몇 덩어리로 흩어져 있는지 (1이면 붙어 있음)."""
        remaining, n = set(cells), 0
        while remaining:
            n += 1
            queue = deque([remaining.pop()])
            while queue:
                for nb in spec.neighbors_of(queue.popleft()):
                    if nb in remaining:
                        remaining.discard(nb)
                        queue.append(nb)
        return n

    @staticmethod
    def _wall_length(spec: BuildingSpec, cells: set[int]) -> int:
        """방을 둘러싼 벽 길이(셀 단위) — 짧을수록 반듯한 형태."""
        length = 0
        for i in cells:
            length += 4 - sum(1 for nb in spec.neighbors_of(i) if nb in cells)
        return length

    # --- 평가 지표 -------------------------------------------------------
    def raw_terms(self, spec: BuildingSpec) -> dict[str, float]:
        """가중치 적용 전 12개 항의 정규화 값 (terms.raw_values 위임)."""
        return raw_values(spec, self.assignment)

    def score(self, spec: BuildingSpec, w: EnvWeights) -> float:
        """환경 변수를 적용한 최종 에너지. 낮을수록 좋은 도면."""
        return score_from_values(raw_values(spec, self.assignment), w)

    def is_feasible(self, spec: BuildingSpec) -> bool:
        t = self.raw_terms(spec)
        return t["cell_violation"] == 0 and t["area_error"] == 0

    # --- 보정 -----------------------------------------------------------
    def repair(self, spec: BuildingSpec) -> "FloorPlan":
        """빈 셀을 메우고 방 면적을 요구치에 맞춘다.

        LLM이 만든 도면이나 D-Wave의 원시 샘플은 셀이 비거나 면적이 어긋날 수
        있다. 인접한 방에 셀을 넘겨주는 식으로 최소 수정만 가한다.
        """
        a = list(self.assignment)

        # (1) 빈 셀을 이웃 방 중 가장 부족한 방에게 준다
        for _ in range(spec.n_cells):
            empties = [i for i, k in enumerate(a) if k is None]
            if not empties:
                break
            progressed = False
            for i in empties:
                cand = {a[nb] for nb in spec.neighbors_of(i) if a[nb] is not None}
                if not cand:
                    continue
                deficit = {
                    k: spec.room_by_key[k].area - sum(1 for v in a if v == k)
                    for k in cand
                }
                a[i] = max(deficit, key=lambda k: deficit[k])
                progressed = True
            if not progressed:  # 완전히 빈 도면 → 아무 방이나 심는다
                a[empties[0]] = spec.room_keys[0]

        # (2) 면적 초과분을 부족한 이웃 방에게 넘긴다
        for _ in range(spec.n_cells * 4):
            counts = {k: sum(1 for v in a if v == k) for k in spec.room_keys}
            over = [k for k in spec.room_keys if counts[k] > spec.room_by_key[k].area]
            under = [k for k in spec.room_keys if counts[k] < spec.room_by_key[k].area]
            if not over or not under:
                break
            moved = False
            for i, key in enumerate(a):
                if key not in over:
                    continue
                # 넘겨줄 대상: 이 셀에 맞닿아 있고 면적이 부족한 방
                targets = [
                    a[nb] for nb in spec.neighbors_of(i)
                    if a[nb] in under and a[nb] != key
                ]
                if targets:
                    a[i] = targets[0]
                    moved = True
                    break
            if not moved:  # 맞닿은 곳이 없으면 아무 셀이나 강제 이전
                for i, key in enumerate(a):
                    if key in over:
                        a[i] = under[0]
                        moved = True
                        break
            if not moved:
                break

        return FloorPlan(self.spec_key, self.name, a, self.source, dict(self.meta))

    # --- 직렬화 ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "spec_key": self.spec_key,
            "name": self.name,
            "source": self.source,
            "assignment": self.assignment,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FloorPlan":
        return cls(d["spec_key"], d["name"], d["assignment"], d.get("source", "unknown"), d.get("meta", {}))

    def to_ascii(self, spec: BuildingSpec) -> str:
        sym = {r.key: r.name[0] for r in spec.rooms}
        rows = []
        for row in self.grid(spec):
            rows.append(" ".join(sym.get(k, "·") if k else "·" for k in row))
        return "\n".join(rows)


def save_plans(plans: list[FloorPlan], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in plans], f, ensure_ascii=False, indent=2)


def load_plans(path: str) -> list[FloorPlan]:
    with open(path, encoding="utf-8") as f:
        return [FloorPlan.from_dict(d) for d in json.load(f)]
