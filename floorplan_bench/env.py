"""3단계 — "좋은 도면은 무엇인가"를 수치로 기록한 환경 변수 12개.

    E(도면) = Σ_i  sign_i · w_i · term_i(도면)

sign은 항의 성격이 결정한다(보상이면 −1, 벌점이면 +1). w가 설계 방침이다.
항의 정의와 정규화는 terms.py에, 여기에는 '무엇을 얼마나 중시할 것인가'만 둔다.

10개 프리셋은 각각 다른 설계 방침을 대표한다. 같은 방 프로그램에 다른 프리셋을
적용하면 최적 도면이 달라진다 — 그것이 이 실험의 독립 변수다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EnvWeights:
    key: str
    name: str
    description: str

    # ── 하드 제약 벌점 ─────────────────────────────────────
    p_cell: float = 20.0   # 셀 배타성 위반
    p_area: float = 12.0   # 요구 면적 이탈

    # ── 2차 항 (셀 쌍 위에서 계산) ──────────────────────────
    w_adjacency: float = 6.0    # 인접 선호 충족          (보상)
    w_compactness: float = 6.0  # 방 응집도               (보상)
    w_corridor: float = 4.0     # 동선 코어 접면          (보상)
    w_noise: float = 4.0        # 소음 인접               (벌점)

    # ── 1차 항 (셀 하나씩 계산) ────────────────────────────
    w_daylight: float = 3.0     # 채광 확보               (보상)
    w_solar: float = 2.0        # 남향 확보               (보상)
    w_privacy: float = 3.0      # 프라이버시              (보상)
    w_circulation: float = 3.0  # 공용 접근성             (보상)
    w_plumbing: float = 2.0     # 설비 코어 집중          (보상)
    w_thermal: float = 2.0      # 외피 노출               (벌점)

    def as_dict(self) -> dict:
        return asdict(self)

    def scaled(self, **overrides) -> "EnvWeights":
        return EnvWeights(**{**asdict(self), **overrides})


def _p(key, name, description, **over) -> EnvWeights:
    return EnvWeights(key=key, name=name, description=description, **over)


PRESETS: dict[str, EnvWeights] = {
    "balanced": _p(
        "balanced", "균형형",
        "열 개 지표를 고르게 본다. 다른 프리셋의 기준선(baseline)."),
    "family": _p(
        "family", "가족 동선 중심",
        "거실-주방-현관으로 이어지는 생활 동선과 방 사이 인접 관계를 최우선한다.",
        w_adjacency=12.0, w_circulation=6.0, w_corridor=6.0,
        w_compactness=5.0, w_privacy=1.5, w_solar=1.0),
    "daylight": _p(
        "daylight", "채광 우선",
        "창이 필요한 모든 방을 외벽에 붙인다. 방위는 따지지 않는다.",
        w_daylight=10.0, w_adjacency=4.0, w_compactness=5.0,
        w_privacy=1.5, w_thermal=1.0),
    "solar": _p(
        "solar", "남향 극대화",
        "채광 실을 남측 외벽에 몰아 넣는다. 한국 주거의 전형적 요구.",
        w_solar=10.0, w_daylight=4.0, w_adjacency=4.0,
        w_compactness=5.0, w_circulation=2.0),
    "privacy": _p(
        "privacy", "프라이버시 우선",
        "침실·욕실을 현관 동선에서 최대한 떼어 놓는다. 1인 가구/셰어형.",
        w_privacy=10.0, w_adjacency=5.0, w_compactness=5.0,
        w_circulation=1.5, w_corridor=2.0),
    "acoustic": _p(
        "acoustic", "정온 우선",
        "주방·거실의 소음이 침실에 닿지 않도록 완충한다. 재택근무·다세대.",
        w_noise=14.0, w_adjacency=4.0, w_compactness=5.0, w_privacy=4.0),
    "passive": _p(
        "passive", "패시브 에너지",
        "창이 필요 없는 방의 외피 노출을 줄여 열손실을 억제하고, 남향은 살린다.",
        w_thermal=10.0, w_solar=5.0, w_daylight=4.0,
        w_compactness=7.0, w_adjacency=3.0),
    "plumbing": _p(
        "plumbing", "설비 효율",
        "급배수 실을 수직 배관 코어에 모아 배관 연장을 줄인다. 공사비 직결.",
        w_plumbing=10.0, w_compactness=6.0, w_adjacency=4.0,
        w_corridor=3.0, w_daylight=2.0),
    "buildable": _p(
        "buildable", "시공 효율",
        "방이 반듯한 덩어리로 뭉치는 것을 최우선한다. 벽 길이·공사비 절감.",
        w_compactness=16.0, w_adjacency=4.0, w_daylight=2.0,
        w_privacy=1.5, w_circulation=1.5, w_solar=1.0),
    "barrier_free": _p(
        "barrier_free", "무장애 접근",
        "모든 방이 복도에 직접 면하게 해 이동 거리를 줄인다. 고령자·휠체어 배려.",
        w_corridor=12.0, w_circulation=5.0, w_compactness=5.0,
        w_adjacency=3.0, w_privacy=1.0),
}


def get_env(key: str) -> EnvWeights:
    if key not in PRESETS:
        raise KeyError(f"알 수 없는 환경 변수 '{key}'. 선택지: {list(PRESETS)}")
    return PRESETS[key]
