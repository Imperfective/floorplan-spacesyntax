"""건물 프로그램(방 구성)과 격자 정의.

파이프라인 전체가 이 격자를 기준으로 동작한다.
격자 셀 인덱스는 i = y * width + x (좌상단이 (0, 0)).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Room:
    """방 하나의 요구 사항."""

    key: str
    name: str
    area: int  # 요구 셀 수
    needs_window: bool = False  # 채광 필요 여부 → 외피(perimeter) 셀 선호
    privacy: float = 0.0  # 1에 가까울수록 현관에서 멀어야 좋다
    public: float = 0.0  # 1에 가까울수록 현관에서 가까워야 좋다
    noise: float = 0.0  # 소음을 내는 정도 (주방·거실이 높다)
    quiet: float = 0.0  # 정숙을 요구하는 정도 (침실이 높다)
    wet: bool = False  # 급배수 설비 필요 (욕실·주방·다용도실)
    color: str = "#d9d9d9"


@dataclass
class BuildingSpec:
    """격자 + 방 프로그램 + 방 사이 인접 선호도."""

    key: str
    name: str
    width: int
    height: int
    rooms: list[Room]
    entrance: tuple[int, int]
    # (방 A, 방 B) -> 선호도. 양수는 붙이고 싶다, 음수는 떼어놓고 싶다.
    adjacency: dict[tuple[str, str], float] = field(default_factory=dict)
    plumbing_core: tuple[int, int] | None = None  # 배관 수직 코어 위치
    core_room: str = "hall"  # 복도 접근성을 재는 기준이 되는 동선 코어 실

    def __post_init__(self) -> None:
        self.n_cells = self.width * self.height
        self.cells = list(range(self.n_cells))
        self.room_keys = [r.key for r in self.rooms]
        self.room_by_key = {r.key: r for r in self.rooms}

        total_area = sum(r.area for r in self.rooms)
        if total_area != self.n_cells:
            raise ValueError(
                f"방 면적 합({total_area})이 격자 셀 수({self.n_cells})와 다릅니다."
            )

        ex, ey = self.entrance
        self._entrance_idx = self.idx(ex, ey)

        # 인접 선호도를 정렬된 키로 정규화
        self._adj = {}
        for (a, b), w in self.adjacency.items():
            if a not in self.room_by_key or b not in self.room_by_key:
                raise ValueError(f"알 수 없는 방 키: {(a, b)}")
            self._adj[tuple(sorted((a, b)))] = w

        # 파생 구조 (한 번만 계산)
        self._neighbor_pairs = self._build_neighbor_pairs()
        self._perimeter = [self._is_perimeter(i) for i in self.cells]
        max_d = max(self._manhattan(i) for i in self.cells) or 1
        self._entrance_dist = [self._manhattan(i) / max_d for i in self.cells]

        # 남향 = 격자의 아래쪽 변(y = height-1)
        self._south = [self.xy(i)[1] == self.height - 1 for i in self.cells]

        # 배관 코어까지의 정규화 거리
        if self.plumbing_core is None:
            self.plumbing_core = (self.width - 1, 0)
        px, py = self.plumbing_core
        raw = [abs(self.xy(i)[0] - px) + abs(self.xy(i)[1] - py) for i in self.cells]
        mx = max(raw) or 1
        self._core_dist = [v / mx for v in raw]

    # --- 좌표 변환 -------------------------------------------------------
    def idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def xy(self, i: int) -> tuple[int, int]:
        return i % self.width, i // self.width

    def _manhattan(self, i: int) -> int:
        x, y = self.xy(i)
        ex, ey = self.entrance
        return abs(x - ex) + abs(y - ey)

    def _is_perimeter(self, i: int) -> bool:
        x, y = self.xy(i)
        return x == 0 or y == 0 or x == self.width - 1 or y == self.height - 1

    def _build_neighbor_pairs(self) -> list[tuple[int, int]]:
        """상하좌우로 맞닿은 셀 쌍(중복 없이 i < j)."""
        pairs = []
        for y in range(self.height):
            for x in range(self.width):
                i = self.idx(x, y)
                if x + 1 < self.width:
                    pairs.append((i, self.idx(x + 1, y)))
                if y + 1 < self.height:
                    pairs.append((i, self.idx(x, y + 1)))
        return pairs

    # --- 조회 ------------------------------------------------------------
    @property
    def neighbor_pairs(self) -> list[tuple[int, int]]:
        return self._neighbor_pairs

    @property
    def entrance_idx(self) -> int:
        return self._entrance_idx

    def is_perimeter(self, i: int) -> bool:
        return self._perimeter[i]

    def entrance_dist(self, i: int) -> float:
        """현관까지의 정규화 거리(0 = 현관, 1 = 가장 먼 셀)."""
        return self._entrance_dist[i]

    def is_south(self, i: int) -> bool:
        """남향 외벽에 면한 셀인가."""
        return self._south[i]

    def core_dist(self, i: int) -> float:
        """배관 코어까지의 정규화 거리(0 = 코어, 1 = 가장 먼 셀)."""
        return self._core_dist[i]

    def adj_weight(self, a: str, b: str) -> float:
        return self._adj.get(tuple(sorted((a, b))), 0.0)

    def adjacency_pairs(self) -> list[tuple[str, str, float]]:
        """선호도가 0이 아닌 방 쌍만."""
        return [(a, b, w) for (a, b), w in sorted(self._adj.items()) if w != 0.0]

    def neighbors_of(self, i: int) -> list[int]:
        x, y = self.xy(i)
        out = []
        if x > 0:
            out.append(self.idx(x - 1, y))
        if x + 1 < self.width:
            out.append(self.idx(x + 1, y))
        if y > 0:
            out.append(self.idx(x, y - 1))
        if y + 1 < self.height:
            out.append(self.idx(x, y + 1))
        return out


# --- 내장 프로그램 -------------------------------------------------------

SMALL_6X6 = BuildingSpec(
    key="small_6x6",
    name="원룸형 소형 주택 (6×6 = 36셀)",
    width=6,
    height=6,
    entrance=(0, 5),
    plumbing_core=(5, 0),
    rooms=[
        Room("hall", "현관·복도", 4, False, 0.0, 1.0, 0.2, 0.0, False, "#b8b8b8"),
        Room("living", "거실", 10, True, 0.1, 0.9, 0.8, 0.2, False, "#8ecae6"),
        Room("kitchen", "주방", 6, True, 0.2, 0.6, 1.0, 0.0, True, "#ffb703"),
        Room("bed", "침실", 8, True, 0.9, 0.0, 0.1, 1.0, False, "#a8dadc"),
        Room("bath", "욕실", 4, False, 0.7, 0.1, 0.4, 0.1, True, "#cdb4db"),
        Room("store", "창고", 4, False, 0.3, 0.2, 0.5, 0.0, True, "#c7c7a6"),
    ],
    adjacency={
        ("living", "kitchen"): 1.0,
        ("living", "hall"): 0.8,
        ("bed", "bath"): 0.7,
        ("living", "bed"): 0.3,
        ("hall", "bath"): 0.2,
        ("kitchen", "store"): 0.4,
        ("kitchen", "bath"): -0.6,  # 위생상 붙이지 않는다
        ("hall", "bed"): -0.5,  # 현관에서 침실이 바로 보이면 안 된다
        ("kitchen", "bed"): -0.3,
    },
)

APARTMENT_8X8 = BuildingSpec(
    key="apartment_8x8",
    name="34평형 아파트 (8×8 = 64셀)",
    width=8,
    height=8,
    entrance=(0, 7),
    plumbing_core=(7, 0),
    rooms=[
        Room("hall", "현관·복도", 9, False, 0.0, 1.0, 0.2, 0.0, False, "#b8b8b8"),
        Room("living", "거실", 14, True, 0.1, 0.9, 0.8, 0.2, False, "#8ecae6"),
        Room("kitchen", "주방·식당", 8, True, 0.2, 0.6, 1.0, 0.0, True, "#ffb703"),
        Room("master", "안방", 12, True, 0.9, 0.0, 0.1, 1.0, False, "#a8dadc"),
        Room("bed2", "작은방", 9, True, 0.8, 0.0, 0.2, 0.9, False, "#bde0fe"),
        Room("bath", "욕실", 6, False, 0.7, 0.1, 0.4, 0.1, True, "#cdb4db"),
        Room("store", "다용도실", 6, False, 0.3, 0.2, 0.5, 0.0, True, "#c7c7a6"),
    ],
    adjacency={
        ("living", "kitchen"): 1.0,
        ("living", "hall"): 0.8,
        ("master", "bath"): 0.7,
        ("bed2", "bath"): 0.5,
        ("living", "master"): 0.3,
        ("living", "bed2"): 0.3,
        ("hall", "bath"): 0.2,
        ("kitchen", "store"): 0.4,
        ("kitchen", "bath"): -0.6,
        ("hall", "master"): -0.5,
        ("kitchen", "master"): -0.4,
        ("master", "bed2"): -0.2,  # 침실끼리는 소음 분리
    },
)

SPECS = {s.key: s for s in (SMALL_6X6, APARTMENT_8X8)}
