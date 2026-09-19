"""1단계 — AI가 건물 도면을 생성한다.

백엔드 두 가지:
  * claude     : Claude(claude-opus-5)가 구조화 출력으로 방 사각형을 배치한다.
  * procedural : BSP(이진 공간 분할) 기반 생성기. 자격 증명 없이도 항상 동작한다.

두 백엔드 모두 "사각형 목록"이라는 같은 형식을 내놓고, 이후 단계는 이를
FloorPlan.from_rects()로 받아 동일하게 처리한다.
"""

from __future__ import annotations

import os
import random
import subprocess

from .plan import FloorPlan
from .spec import BuildingSpec

MODEL = "claude-opus-5"


# ============================================================ 절차적 생성기
def _bsp(spec, x, y, w, h, rooms, rng, rects) -> None:
    """영역을 방 면적 비율대로 재귀 분할한다."""
    if not rooms:
        return
    if len(rooms) == 1 or w * h <= 1:
        rects.append({"room": rooms[0].key, "x": x, "y": y, "w": w, "h": h})
        for extra in rooms[1:]:  # 자리가 없으면 1셀만 심어 두고 repair에 맡긴다
            rects.append({"room": extra.key, "x": x, "y": y, "w": 1, "h": 1})
        return

    rooms = list(rooms)
    rng.shuffle(rooms)
    k = rng.randint(1, len(rooms) - 1)
    total = sum(r.area for r in rooms)
    ratio = sum(r.area for r in rooms[:k]) / total

    vertical = w >= h if w > 1 and h > 1 else w > 1
    if vertical:
        cut = min(max(round(w * ratio), 1), w - 1)
        _bsp(spec, x, y, cut, h, rooms[:k], rng, rects)
        _bsp(spec, x + cut, y, w - cut, h, rooms[k:], rng, rects)
    else:
        cut = min(max(round(h * ratio), 1), h - 1)
        _bsp(spec, x, y, w, cut, rooms[:k], rng, rects)
        _bsp(spec, x, y + cut, w, h - cut, rooms[k:], rng, rects)


def generate_procedural(spec: BuildingSpec, n: int, seed: int = 0) -> list[FloorPlan]:
    plans = []
    for i in range(n):
        rng = random.Random(seed + i)
        rects: list[dict] = []
        _bsp(spec, 0, 0, spec.width, spec.height, list(spec.rooms), rng, rects)
        plan = FloorPlan.from_rects(spec, rects, f"절차적 #{i + 1}", "procedural")
        plans.append(plan.repair(spec))
    return plans


# ================================================================ Claude 생성
def has_anthropic_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:  # `ant auth login`으로 저장된 프로필도 SDK가 자동으로 읽는다
        r = subprocess.run(
            ["ant", "auth", "status"], capture_output=True, timeout=10, text=True
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def _brief(spec: BuildingSpec, env_note: str) -> str:
    rooms = "\n".join(
        f"  - {r.key} ({r.name}): {r.area}셀"
        f"{', 채광 필요' if r.needs_window else ''}"
        f", 사적도 {r.privacy}, 공용도 {r.public}"
        for r in spec.rooms
    )
    adj = "\n".join(
        f"  - {a} ↔ {b}: {'선호' if wgt > 0 else '기피'} ({wgt:+.1f})"
        for a, b, wgt in spec.adjacency_pairs()
    )
    ex, ey = spec.entrance
    return f"""{spec.width}×{spec.height} 격자({spec.n_cells}셀) 위에 주거 평면을 배치하세요.
좌표는 좌상단이 (0,0), x는 오른쪽, y는 아래 방향입니다. 현관 위치는 ({ex},{ey})입니다.
격자 바깥 테두리에 닿는 셀만 외벽(창을 낼 수 있는 곳)입니다.

방 프로그램(요구 면적의 합은 정확히 {spec.n_cells}셀):
{rooms}

방 사이 인접 선호도:
{adj}

설계 방침: {env_note}

규칙:
  - 각 방을 축에 정렬된 직사각형 하나로 배치합니다.
  - 사각형끼리 겹치지 않고 격자를 빈틈없이 덮어야 합니다.
  - 각 방의 면적(w×h)을 요구 면적에 최대한 맞춥니다.
  - 서로 다른 배치 전략을 쓴 안을 내놓으세요(중앙 복도형, 측면 복도형, 존 분리형 등).
"""


def generate_with_claude(
    spec: BuildingSpec, n: int, env_note: str = "균형 잡힌 일반 주거"
) -> list[FloorPlan]:
    """Claude에게 서로 다른 배치 전략의 도면 n장을 받아온다."""
    import anthropic
    from pydantic import BaseModel, Field

    class Rect(BaseModel):
        room: str = Field(description="방 키(room key)")
        x: int
        y: int
        w: int
        h: int

    class Candidate(BaseModel):
        name: str = Field(description="배치 전략을 나타내는 짧은 한국어 이름")
        rationale: str = Field(description="이 배치를 택한 이유 한두 문장")
        rects: list[Rect]

    class PlanSet(BaseModel):
        plans: list[Candidate]

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system="당신은 주거 평면 계획에 밝은 건축 설계자입니다. 격자 위에 방을 배치합니다.",
        messages=[
            {
                "role": "user",
                "content": _brief(spec, env_note)
                + f"\n서로 뚜렷하게 다른 배치안을 정확히 {n}개 만들어 주세요.",
            }
        ],
        output_format=PlanSet,
    )

    plans = []
    for i, cand in enumerate(response.parsed_output.plans[:n]):
        rects = [r.model_dump() for r in cand.rects]
        plan = FloorPlan.from_rects(
            spec, rects, f"Claude · {cand.name}", "claude"
        )
        plan.meta["rationale"] = cand.rationale
        plans.append(plan.repair(spec))
    return plans


# ==================================================================== 진입점
def generate_plans(
    spec: BuildingSpec,
    n: int = 6,
    backend: str = "auto",
    env_note: str = "균형 잡힌 일반 주거",
    seed: int = 0,
) -> tuple[list[FloorPlan], str]:
    """도면 n장을 만들고 (도면 목록, 실제 사용한 백엔드)를 돌려준다."""
    if backend == "procedural":
        return generate_procedural(spec, n, seed), "procedural"

    if backend in ("claude", "auto"):
        if backend == "auto" and not has_anthropic_credentials():
            return generate_procedural(spec, n, seed), "procedural (자격 증명 없음)"
        try:
            plans = generate_with_claude(spec, n, env_note)
            if plans:
                # 다양성 확보를 위해 절차적 생성 도면을 조금 섞는다
                extra = max(0, n - len(plans))
                if extra:
                    plans += generate_procedural(spec, extra, seed)
                return plans, "claude"
        except Exception as exc:  # 네트워크/인증/스키마 문제 → 절차적 생성으로 대체
            if backend == "claude":
                raise
            print(f"  ! Claude 생성 실패({type(exc).__name__}: {exc}) → 절차적 생성으로 대체")
    return generate_procedural(spec, n, seed), "procedural (대체)"
