"""AI 허브 라벨 평가기 — 합성 도면으로 각 검사가 실제로 걸리는지 확인한다.

    python -m pytest tests/test_aihub_eval.py   (pytest 없으면: python tests/test_aihub_eval.py)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from floorplan_bench.aihub import load_struct, load_units  # noqa: E402
from floorplan_bench.evaluate import evaluate, struct_checks  # noqa: E402

M = 100  # px/m
W = 20   # 벽 두께(px)

# 3R1B 기본 평면 (m 단위 사각형, x, y, w, h). 실 사이에 벽 두께만큼 틈을 둔다.
GOOD = [
    (16, "entry",   0, 4, 2, 2),
    (13, "living",  2, 0, 6, 6),
    (15, "kitchen", 8, 0, 3, 3),
    (18, "bath",    8, 3, 3, 3),
    (14, "bed",     2, 6, 3, 3),     # 거실 남쪽 — 외기 접함
    (14, "bed",     5, 6, 3, 3),
    (14, "bed",    -3, 2, 3, 4),     # 서쪽 — 외기 접함, 현관과 2m 맞닿음
]


def coco(rooms, extra=()):
    anns = []
    for i, (cid, _, x, y, w, h) in enumerate(list(rooms) + list(extra)):
        x0, y0 = x * M + W / 2, y * M + W / 2
        x1, y1 = (x + w) * M - W / 2, (y + h) * M - W / 2
        anns.append({"id": i, "image_id": 1, "category_id": cid,
                     "segmentation": [[x0, y0, x1, y0, x1, y1, x0, y1]],
                     "area": (x1 - x0) * (y1 - y0), "bbox": [x0, y0, x1 - x0, y1 - y0],
                     "iscrowd": 0, "attributes": {"occluded": False}})
    return {"images": [{"id": 1, "width": 4000, "height": 3000}], "categories": [], "annotations": anns}


def run(rooms, name="APT_FP_SPA_test.json"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(coco(rooms), f)
        units = load_units(p)
    assert len(units) == 1
    r = evaluate(units[0])
    return {i["id"] for i in r["feasibility"]["issues"] if i["level"] != "info"}, r


def test_good_plan_passes():
    ids, r = run(GOOD)
    assert r["feasibility"]["pass"], r["feasibility"]["issues"]
    assert ids == set()
    assert r["type"] == "3R1B"
    # 거실이 가장 통합된 공간
    assert r["features"]["living_int_rank"] == 1


def test_missing_kitchen_F1():
    ids, _ = run([g for g in GOOD if g[1] != "kitchen"])
    assert "F1" in ids


def test_overlap_F2():
    ids, _ = run(GOOD + [(14, "bed", 3, 1, 3, 3)])   # 거실 한가운데 침실
    assert "F2" in ids


def test_isolated_room_F3():
    # 침실 아래 0.5m 떨어진 화장실 — 벽 하나 두께보다 멀어 어떤 실과도 맞닿지 않는다
    ids, r = run(GOOD + [(18, "bath", 2, 9.5, 2, 2)])
    assert "F3" in ids
    # 아주 멀리 떨어진 것은 다른 그림으로 보고 세대에 넣지 않는다
    _, r = run(GOOD + [(14, "bed", 40, 20, 3, 3)])
    assert r["type"] == "3R1B"


def test_bedroom_through_bedroom_F4():
    # 침실 b3은 다른 침실(b2)에만 맞닿는다
    ids, _ = run(GOOD + [(14, "bed", 5, 9, 3, 3)])
    assert "F4" in ids


def test_kitchen_bath_F5():
    # 화장실을 주방에만 붙인다(거실과는 떨어뜨림)
    rooms = [g for g in GOOD if g[1] != "bath"] + [(18, "bath", 11, 0, 2, 3)]
    ids, _ = run(rooms)
    assert "F5" in ids


def test_no_daylight_F6():
    # 사방이 다른 실로 둘러싸인 침실
    rooms = [
        (16, "entry", 0, 0, 2, 2), (13, "living", 2, 0, 3, 9), (15, "kitchen", 8, 0, 3, 9),
        (14, "bed", 5, 3, 3, 3), (18, "bath", 5, 0, 3, 3), (20, "dress", 5, 6, 3, 3),
    ]
    ids, _ = run(rooms)
    assert "F6" in ids


def test_door_window_overlap_F8():
    d = {"images": [{"id": 1}], "categories": [], "annotations": [
        {"id": 1, "category_id": 9, "bbox": [100, 100, 90, 20], "segmentation": [[100, 100, 190, 100, 190, 120, 100, 120]],
         "attributes": {"구조_출입문": "여닫이문"}},
        {"id": 2, "category_id": 10, "bbox": [120, 100, 150, 20], "segmentation": [[120, 100, 270, 100, 270, 120, 120, 120]],
         "attributes": {"창호": "미닫이창"}},
        {"id": 3, "category_id": 10, "bbox": [500, 100, 150, 20], "segmentation": [],
         "attributes": {"창호": "미닫이창"}},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "APT_FP_STR_test.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
        iss = struct_checks(load_struct(p))
    assert [(i["door"], i["window"]) for i in iss] == [(1, 2)]


def test_two_units_split():
    shifted = [(c, k, x + 30, y, w, h) for c, k, x, y, w, h in GOOD]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "APT_FP_SPA_two.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(coco(GOOD + shifted), f)
        assert len(load_units(p)) == 2


# ═══ 사용자 조건(criteria) — 넣고 빼고 반영방식 바꾸기
def test_criteria_roundtrip_and_effects():
    from floorplan_bench.criteria import Config, Criterion, parse_dsl, score_all, to_dsl
    text = """@unlit_rooms <= 0 as=penalty:20   # 채광
bed.aspect <= 2 .. 4 w=2 agg=mean
master.step_depth == 3 ± 1
#! @n_bed >= 3 as=gate
"""
    cs, errs = parse_dsl(text)
    assert not errs and len(cs) == 4 and not cs[3].enabled
    assert cs[0].mode == "pass" and cs[0].effect == "penalty" and cs[0].penalty == 20
    assert cs[1].mode == "range" and cs[1].agg == "mean" and cs[1].weight == 2
    again, errs = parse_dsl(to_dsl(cs))
    assert not errs and [c.as_dict() for c in again] == [c.as_dict() for c in cs]
    # 웹이 내보내는 JSON(조건 배열)도 그대로 읽힌다
    assert [Criterion.from_dict(c.as_dict()) for c in cs] == cs

    m = {"global": {"unlit_rooms": 1, "n_bed": 2},
         "rooms": {"b1": {"kind": "bed", "area_ratio": .2, "aspect": 3.0, "step_depth": 3},
                   "b2": {"kind": "bed", "area_ratio": .1, "aspect": 2.0, "step_depth": 2}}}
    r = score_all(cs, m)
    # bed.aspect 평균 (0.5+1)/2=0.75 (w=2), 안방 b1 깊이 3 → 1.0 (w=1) → 기본점 (1.5+1)/3
    assert abs(r["base"] - 2.5 / 3 * 100) < 1e-9
    assert r["penalty"] == 20 and r["gated"] == 0          # 꺼 둔 gate는 무시
    cs[3].enabled = True
    assert score_all(cs, m)["total"] == 0                   # 켜면 침실 2개라 탈락
    assert parse_dsl("bed.typicality <= 1")[1]               # 전역 지표를 실에 쓰면 오류


def test_params_change_inference():
    from floorplan_bench.criteria import Config, parse_dsl
    from floorplan_bench.evaluate import EvalParams
    _, r = run(GOOD)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "APT_FP_SPA_x.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(coco(GOOD + [(17, "balcony", 2, 9, 6, 1.4)]), f)
        u = load_units(p)[0]
    leaf = evaluate(u, rules=EvalParams(balcony="leaf"))
    allb = evaluate(u, rules=EvalParams(balcony="all"))
    none = evaluate(u, rules=EvalParams(balcony="none"))
    assert len(allb["doors_inferred"]) > len(leaf["doors_inferred"]) > len(none["doors_inferred"])
    cfg = Config(criteria=parse_dsl("@n_spaces <= 7 as=gate")[0])
    assert evaluate(u, rules=EvalParams(balcony="none"), config=cfg)["score"]["total"] == 100
    assert evaluate(u, rules=EvalParams(balcony="leaf"), config=cfg)["score"]["total"] == 0


def test_stats_aggregate():
    from floorplan_bench.criteria import Config
    from floorplan_bench.stats import aggregate, stat_row
    rows = []
    for name, rooms in (("a.json", GOOD), ("b.json", [g for g in GOOD if g[1] != "kitchen"])):
        _, r = run(rooms, "APT_FP_SPA_" + name)
        rows.append(stat_row(r, name))
    s = aggregate(rows, Config(), name="t", memo="m")
    assert s["kind"] == "aihub-stats" and s["summary"]["n_units"] == 2 and s["summary"]["n_files"] == 2
    assert sum(h["n"] for h in s["summary"]["histogram"]) == 2
    assert s["summary"]["gated_rate"] == 0.5                       # 주방 없는 세대는 필수 조건 탈락
    assert next(i for i in s["issues"] if i["id"] == "F1")["units"] == 1
    assert len(s["criteria"]) == len([c for c in Config().criteria if c.enabled])
    assert s["config"]["dsl"] and s["units"][1]["total"] == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
