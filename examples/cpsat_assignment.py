"""OR-Tools CP-SAT 간단 예제 — 작업 배정 문제(Assignment Problem).

작업자 4명에게 작업 4개를 1:1로 배정할 때 총 비용이 최소가 되는 조합을 찾는다.

실행:
    source .venv/bin/activate && python example.py
    # 또는
    uv run python example.py
"""

from ortools.sat.python import cp_model

WORKERS = ["김주임", "이대리", "박과장", "최사원"]
TASKS = ["설계", "구현", "테스트", "배포"]

# COST[w][t] = 작업자 w가 작업 t를 맡을 때 드는 비용(예: 소요 시간)
COST = [
    [90, 80, 75, 70],
    [35, 85, 55, 65],
    [125, 95, 90, 95],
    [45, 110, 95, 115],
]


def main() -> None:
    model = cp_model.CpModel()

    # 1) 변수 — x[w, t]가 1이면 작업자 w가 작업 t를 맡는다
    x = {
        (w, t): model.new_bool_var(f"x[{w},{t}]")
        for w in range(len(WORKERS))
        for t in range(len(TASKS))
    }

    # 2) 제약
    for w in range(len(WORKERS)):  # 작업자마다 정확히 1개 작업
        model.add_exactly_one(x[w, t] for t in range(len(TASKS)))
    for t in range(len(TASKS)):  # 작업마다 정확히 1명 담당
        model.add_exactly_one(x[w, t] for w in range(len(WORKERS)))

    # 3) 목적함수 — 총 비용 최소화
    model.minimize(
        sum(
            COST[w][t] * x[w, t]
            for w in range(len(WORKERS))
            for t in range(len(TASKS))
        )
    )

    # 4) 풀기
    solver = cp_model.CpSolver()
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"해를 찾지 못했습니다: {solver.status_name(status)}")
        return

    print(f"상태: {solver.status_name(status)}   총 비용: {solver.objective_value:.0f}")
    print("-" * 34)
    for w in range(len(WORKERS)):
        for t in range(len(TASKS)):
            if solver.boolean_value(x[w, t]):
                print(f"  {WORKERS[w]}  →  {TASKS[t]:<4}  (비용 {COST[w][t]})")
    print("-" * 34)
    print(f"탐색 시간: {solver.wall_time:.3f}s")


if __name__ == "__main__":
    main()
