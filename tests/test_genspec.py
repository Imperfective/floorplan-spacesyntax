"""생성 사양(docs/data/aihub-genspec.json) → BuildingSpec 이 생성기에 바로 들어가는지.

    python tests/test_genspec.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from floorplan_bench.genspec import load_genspec, spec_from_genspec  # noqa: E402


def test_strata_build():
    gs = load_genspec()
    assert gs["kind"] == "aihub-genspec" and gs["strata"], "사양이 비었습니다"
    built = 0
    for key, st in gs["strata"].items():
        if st["n"] < 100:
            continue
        spec = spec_from_genspec(gs, key, 12, 12)
        assert sum(r.area for r in spec.rooms) == 144, key            # 격자 셀 수와 같음(BuildingSpec도 검사)
        keys = {r.key for r in spec.rooms}
        assert {"hall", "living", "kitchen"} <= keys, (key, keys)      # 필수 실
        assert all(-1.0 <= w <= 1.0 for w in spec.adjacency.values()), key
        assert all(0.0 <= r.privacy <= 1.0 for r in spec.rooms), key
        built += 1
    assert built >= 5, built
    print(f"ok test_strata_build ({built}개 층)")


def test_3r2b_matches_data():
    gs = load_genspec()
    st = gs["strata"]["3R2B"]
    spec = spec_from_genspec(gs, "3R2B", 10, 10)
    beds = [r for r in spec.rooms if r.key == "master" or r.key.startswith("bed")]
    baths = [r for r in spec.rooms if r.key.startswith("bath")]
    assert len(beds) == 3 and len(baths) == 2, ([r.key for r in spec.rooms])
    # 거실–주방은 실제 도면에서 거의 항상 맞닿는다 → 양의 선호
    lk = st["adjacency"]["kitchen|living"]["wall"]
    assert lk > 0.8 and spec.adj_weight("living", "kitchen") > 0.5, lk
    print("ok test_3r2b_matches_data", {r.key: r.area for r in spec.rooms})


if __name__ == "__main__":
    test_strata_build()
    test_3r2b_matches_data()
