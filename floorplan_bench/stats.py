"""채점 결과를 통계로 모은다 — 웹 스튜디오의 '통계' 탭·보관 기록과 같은 JSON.

    {kind: "aihub-stats", version, created, name, memo,
     config:   {params, criteria, dsl}          # 이 통계를 낸 연구 조건
     baseline: {source, n_units, type_counts}   # 정답지
     summary:  {n_files, n_units, score{n,mean,median,sd,min,max}, histogram[10], grades,
                feasibility_pass_rate, gated_rate, mean_base, mean_penalty}
     by_type:  [{type, n, mean, median, min, max, pass_rate}]
     criteria: [{index, dsl, measure, target, effect, n, skipped, mean_score, full_rate}]
     issues:   [{id, name, units, count}]
     measures: {전역지표: {n, mean, median, sd, min, max}}
     units:    [{unit, file, type, total, base, penalty, gated, grade, pass, issues, global, crit[]}]}

웹(docs/aihub-engine.js의 aggregate)과 같은 계산 — 고칠 때는 둘을 함께 고친다.
"""

from __future__ import annotations

import math
import statistics as st
from datetime import datetime, timezone

from .criteria import MEASURES, Config, to_dsl

ISSUE_IDS = ["F1", "F2", "F3", "F4", "F5", "F6", "F8"]
ISSUE_NAMES = {"F1": "필수실 구성", "F2": "실 겹침 없음", "F3": "출입 불가 실 없음", "F4": "침실 경유 동선 없음",
               "F5": "주방-화장실 직결 없음", "F6": "거실·침실 채광(외기 접면)", "F8": "문·창 겹침 없음 (STR)"}
GRADES = ["A+", "A", "B+", "B", "C+", "C", "D", "F"]


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def stat_row(r: dict, file: str) -> dict:
    """evaluate() 결과 → 통계 한 행 (그림 없이 점수·지표·조건점수만)."""
    iss = r["feasibility"]["issues"]
    return {
        "unit": r["unit"], "file": file, "type": r["type"],
        "total": r["score"]["total"], "base": r["score"]["base"], "penalty": r["score"]["penalty"],
        "gated": r["score"]["gated"], "grade": r["score"]["grade"], "pass": r["feasibility"]["pass"],
        "issues": {i: sum(1 for x in iss if x["id"] == i and x["level"] != "info") for i in ISSUE_IDS},
        "global": {k: (v if _fin(v) else None) for k, v in r["measures"]["global"].items()},
        "crit": [row["score"] for row in r["criteria_rows"]],
    }


def describe(xs) -> dict:
    v = [x for x in xs if _fin(x)]
    if not v:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {"n": len(v), "mean": sum(v) / len(v), "median": st.median(v),
            "sd": st.stdev(v) if len(v) > 1 else None, "min": min(v), "max": max(v)}


def aggregate(rows: list[dict], config: Config, name: str = "", memo: str = "",
              baseline: dict | None = None) -> dict:
    enabled = [c for c in config.criteria if c.enabled]
    totals = [r["total"] for r in rows]
    hist = [{"lo": i * 10, "hi": i * 10 + 10, "n": 0} for i in range(10)]
    for t in totals:
        hist[min(9, int(t // 10))]["n"] += 1
    rate = (lambda f: sum(1 for r in rows if f(r)) / len(rows)) if rows else (lambda f: None)
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    types = []
    for t, rs in by_type.items():
        d = describe([r["total"] for r in rs])
        types.append({"type": t, "n": len(rs), "mean": d["mean"], "median": d["median"], "min": d["min"],
                      "max": d["max"], "pass_rate": sum(1 for r in rs if r["pass"]) / len(rs)})
    types.sort(key=lambda x: (-x["n"], x["type"]))
    crit = []
    for i, c in enumerate(enabled):
        sc = [r["crit"][i] for r in rows if _fin(r["crit"][i])]
        crit.append({"index": i, "dsl": to_dsl([c]).split("   #")[0], "measure": c.measure,
                     "target": c.room if c.scope == "room" else "@", "effect": c.effect,
                     "n": len(sc), "skipped": len(rows) - len(sc), "mean_score": describe(sc)["mean"],
                     "full_rate": (sum(1 for x in sc if x >= 1) / len(sc)) if sc else None})
    return {
        "kind": "aihub-stats", "version": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": name, "memo": memo,
        "config": config.as_dict(),
        "baseline": ({"source": "file", "n_units": baseline.get("n_units"),
                      "type_counts": baseline.get("type_counts")} if baseline else None),
        "summary": {
            "n_files": len({r["file"] for r in rows}), "n_units": len(rows),
            "score": describe(totals), "histogram": hist,
            "grades": {g: sum(1 for r in rows if r["grade"] == g) for g in GRADES},
            "feasibility_pass_rate": rate(lambda r: r["pass"]),
            "gated_rate": rate(lambda r: r["gated"] > 0),
            "mean_base": describe([r["base"] for r in rows])["mean"],
            "mean_penalty": describe([r["penalty"] for r in rows])["mean"],
        },
        "by_type": types,
        "criteria": crit,
        "issues": [{"id": i, "name": ISSUE_NAMES[i], "units": sum(1 for r in rows if r["issues"][i] > 0),
                    "count": sum(r["issues"][i] for r in rows)} for i in ISSUE_IDS],
        "measures": {k: describe([r["global"].get(k) for r in rows])
                     for k, m in MEASURES.items() if m["scope"] == "global"},
        "units": rows,
    }
