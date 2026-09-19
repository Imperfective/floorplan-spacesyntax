"""4단계-A — OR-Tools CP-SAT로 최적 도면을 찾는다 (고전 조합 최적화).

CP-SAT는 "한 셀에 방 하나", "요구 면적 준수" 같은 제약을 **모델의 제약으로**
직접 표현할 수 있다. 페널티로 녹여 넣을 필요가 없다는 것이 QUBO 대비 강점이고,
대신 2차 목적항은 곱 변수로 선형화해야 한다.

mode="native" : 제약은 제약대로, 2차 목적항만 선형화 (CP-SAT다운 방식)
mode="qubo"   : D-Wave가 푸는 것과 완전히 동일한 QUBO를 그대로 최소화 (동일 조건 비교)
"""

from __future__ import annotations

import time

from ortools.sat.python import cp_model

from .env import EnvWeights
from .plan import FloorPlan
from .qubo import build_bqm
from .terms import quality_coeffs
from .spec import BuildingSpec

SCALE = 10**6  # CP-SAT는 정수 목적함수만 다루므로 실수 계수를 정수화한다


def _product_reward(model, y, parts):
    """계수가 음수(보상)일 때: y ≤ 각 항. 최적해에서 자동으로 1이 된다."""
    for expr in parts:
        model.add(y <= expr)


def _product_penalty(model, y, terms):
    """계수가 양수(벌점)일 때: y ≥ Σ항 - (n-1). 위반 시 반드시 1이 된다."""
    for expr, n in terms:
        model.add(y >= expr - (n - 1))


def add_connectivity(model, x, spec: BuildingSpec) -> None:
    """각 방이 반드시 한 덩어리가 되게 강제한다 (단일 상품 유량 정식화).

    방마다 뿌리 셀 하나를 정하고, 그 셀에서 방 크기만큼의 유량을 흘려보내
    모든 셀이 1씩 소비하게 한다. 유량은 같은 방 셀 사이로만 흐를 수 있으므로,
    끊어진 조각에는 유량이 닿지 못해 해가 성립하지 않는다.

    ★ 이 제약이 QUBO/양자 어닐링과의 결정적 차이다. 연결성은 2차식으로 표현할
      수 없어서 D-Wave 쪽에는 이 제약 자체를 넣을 방법이 없다.
    """
    for room in spec.rooms:
        cap = room.area
        root = {c: model.new_bool_var(f"root_{room.key}_{c}") for c in spec.cells}
        model.add_exactly_one(root.values())
        for c in spec.cells:
            model.add(root[c] <= x[room.key, c])

        # 양방향 유량 변수
        flow = {}
        for c, d in spec.neighbor_pairs:
            for u, v in ((c, d), (d, c)):
                f = model.new_int_var(0, cap, f"f_{room.key}_{u}_{v}")
                model.add(f <= cap * x[room.key, u])
                model.add(f <= cap * x[room.key, v])
                flow[(u, v)] = f

        # 유량 보존: 들어온 양 - 나간 양 = (이 셀이 방에 속하면 1) - (뿌리면 area)
        for c in spec.cells:
            inflow = sum(flow[(nb, c)] for nb in spec.neighbors_of(c))
            outflow = sum(flow[(c, nb)] for nb in spec.neighbors_of(c))
            model.add(inflow - outflow == x[room.key, c] - cap * root[c])


def solve_native(
    spec: BuildingSpec,
    w: EnvWeights,
    time_limit: float = 20.0,
    workers: int = 8,
    connected: bool = False,
    hint: list | None = None,
) -> dict:
    model = cp_model.CpModel()

    x = {
        (r, c): model.new_bool_var(f"x_{r}_{c}")
        for r in spec.room_keys
        for c in spec.cells
    }
    obj = []  # (정수 계수, 변수) 목록

    # --- 하드 제약을 네이티브로 -----------------------------------------
    for c in spec.cells:
        model.add_exactly_one(x[r, c] for r in spec.room_keys)
    for room in spec.rooms:
        model.add(sum(x[room.key, c] for c in spec.cells) == room.area)
    if connected:
        add_connectivity(model, x, spec)
    if hint:  # 실현 가능한 출발점을 준다 — 연결성 모델은 첫 해를 찾기가 어렵다
        for c, key in enumerate(hint):
            for r in spec.room_keys:
                model.add_hint(x[r, c], 1 if r == key else 0)

    # --- 목적함수: terms.quality_coeffs 를 그대로 선형화 ---------------------
    # D-Wave가 받는 QUBO의 '품질' 절반과 계수까지 동일하다. 다른 것은 하드 제약을
    # 페널티가 아니라 위의 네이티브 제약으로 표현했다는 점뿐이다.
    lin, quad, const = quality_coeffs(spec, w)
    for (r, c), coeff in lin.items():
        obj.append((round(coeff * SCALE), x[r, c]))
    for (u, v), coeff in quad.items():
        if not coeff:
            continue
        y = model.new_bool_var(f"y_{u}_{v}")
        if coeff < 0:  # 보상 → y를 1로 올릴 수 있을 때만 허용
            _product_reward(model, y, [x[u], x[v]])
        else:  # 벌점 → 둘 다 1이면 반드시 물게 한다
            _product_penalty(model, y, [(x[u] + x[v], 2)])
        obj.append((round(coeff * SCALE), y))

    model.minimize(sum(coeff * var for coeff, var in obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    t0 = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - t0

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "engine": "OR-Tools CP-SAT",
            "mode": "native+연결성" if connected else "native",
            "plan": None,
            "status": solver.status_name(status),
            "wall_time": elapsed,
        }

    assignment = [None] * spec.n_cells
    for (r, c), var in x.items():
        if solver.boolean_value(var):
            assignment[c] = r
    plan = FloorPlan(spec.key, "OR-Tools 최적안", assignment, "ortools")

    bqm = build_bqm(spec, w)
    return {
        "engine": "OR-Tools CP-SAT",
        "mode": "native+연결성" if connected else "native",
        "connected": connected,
        "plan": plan,
        "energy": bqm.energy(plan.to_vector(spec)),
        "status": solver.status_name(status),
        "proven_optimal": status == cp_model.OPTIMAL,
        "objective": solver.objective_value / SCALE + const,
        "best_bound": solver.best_objective_bound / SCALE + const,
        "gap": abs(solver.objective_value - solver.best_objective_bound)
        / max(abs(solver.objective_value), 1e-9),
        "wall_time": elapsed,
        "branches": solver.num_branches,
        "conflicts": solver.num_conflicts,
        "model_vars": len(obj) + len(x),
        "quad_terms": len(quad),
    }


def solve_qubo(
    spec: BuildingSpec, w: EnvWeights, time_limit: float = 20.0, workers: int = 8
) -> dict:
    """D-Wave가 받는 것과 완전히 동일한 QUBO를 CP-SAT로 최소화한다."""
    bqm = build_bqm(spec, w)
    model = cp_model.CpModel()
    v = {var: model.new_bool_var(str(var)) for var in bqm.variables}
    obj = [(round(c * SCALE), v[var]) for var, c in bqm.linear.items() if c]

    for (a, b), c in bqm.quadratic.items():
        if not c:
            continue
        y = model.new_bool_var(f"y_{a}_{b}")
        if c < 0:
            _product_reward(model, y, [v[a], v[b]])
        else:
            _product_penalty(model, y, [(v[a] + v[b], 2)])
        obj.append((round(c * SCALE), y))

    model.minimize(sum(c * var for c, var in obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    t0 = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - t0

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"engine": "OR-Tools CP-SAT", "mode": "qubo", "plan": None,
                "status": solver.status_name(status), "wall_time": elapsed}

    x = {var: int(solver.boolean_value(v[var])) for var in bqm.variables}
    plan = FloorPlan.from_vector(spec, x, "OR-Tools(QUBO) 최적안", "ortools-qubo")
    return {
        "engine": "OR-Tools CP-SAT",
        "mode": "qubo",
        "plan": plan,
        "raw_x": x,
        "energy": bqm.energy(x),
        "status": solver.status_name(status),
        "proven_optimal": status == cp_model.OPTIMAL,
        "objective": solver.objective_value / SCALE + bqm.offset,
        "best_bound": solver.best_objective_bound / SCALE + bqm.offset,
        "wall_time": elapsed,
        "branches": solver.num_branches,
    }


def solve(spec, w, time_limit=20.0, mode="native", workers=8, connected=False,
          hint=None) -> dict:
    if mode == "qubo":
        return solve_qubo(spec, w, time_limit, workers)
    return solve_native(spec, w, time_limit, workers, connected, hint)
