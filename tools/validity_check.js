// 타당성 점검 — 불변성 · 손상 실험 · 판정 기준값 민감도 (실제 라벨 표본)
//   node tools/validity_check.js <APT_FP_SPA 라벨 폴더> [표본 수=300]   (약 5분)
//
// 1) 불변성: 회전 90° · 좌우 반전 · 평행 이동해도 세대 나눔과 점수가 같은가
// 2) 손상 실험: 거실↔안방 라벨 교환(근접도가 떨어져야), 주방 삭제(필수 조건 탈락해야)
// 3) 민감도: 판정 기준값·그래프 규약을 바꿀 때 점수 순위(Kendall τ-b)와 세대 나눔이 얼마나 유지되는가
const fs = require("fs"), path = require("path");
const [dir, nArg] = process.argv.slice(2);
if (!dir) { console.error("사용: node tools/validity_check.js <라벨 폴더> [표본 수]"); process.exit(1); }
const enginePath = path.join(__dirname, "..", "docs", "aihub-engine.js");
const E = require(enginePath);
const N = +nArg || 300;
const files = fs.readdirSync(dir).filter((f) => /^APT_FP_SPA_\d+\.json$/.test(f)).sort();
const step = Math.max(1, Math.floor(files.length / N)), sample = files.filter((_, i) => i % step === 0).slice(0, N);
const crit = E.parseDSL(E.PRESETS["시공가능성 + 공간구문"]).criteria;
const base = JSON.parse(fs.readFileSync(path.join(path.dirname(enginePath), "data", "aihub-baseline.json"), "utf8"));
const load = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
const score = (data, name, params = {}) => E.loadUnits(data, name, params).map((u) => E.scoreUnit(u, E.analyzeUnit(u, params), crit, base, E.scoringParams(params)));
const fin = (v) => v != null && Number.isFinite(v);
function kendall(x, y) {   // τ-b
  let c = 0, d = 0, tx = 0, ty = 0; const n = x.length;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const a = Math.sign(x[i] - x[j]), b = Math.sign(y[i] - y[j]);
    if (a === 0 && b === 0) continue; if (a === 0) { tx++; continue; } if (b === 0) { ty++; continue; }
    if (a === b) c++; else d++;
  }
  return (c - d) / Math.sqrt((c + d + tx) * (c + d + ty));
}
const xform = (data, fn) => {
  const d = JSON.parse(JSON.stringify(data));
  for (const a of d.annotations) {
    if (a.segmentation && a.segmentation[0]) { const s = a.segmentation[0]; for (let i = 0; i + 1 < s.length; i += 2) { const [x, y] = fn(s[i], s[i + 1]); s[i] = x; s[i + 1] = y; } }
    if (a.bbox) { const [x, y, w, h] = a.bbox, p = [fn(x, y), fn(x + w, y), fn(x, y + h), fn(x + w, y + h)]; const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]); a.bbox = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)]; }
  }
  return d;
};

// 1) 불변성 — 회전 90° · 좌우 반전 · 평행 이동
const inv = { rot90: (x, y) => [-y, x], mirror: (x, y) => [-x, y], shift: (x, y) => [x + 1234.5, y - 777.25] };
const invRes = {};
for (const [k, fn] of Object.entries(inv)) {
  let units = 0, sameSplit = 0, maxTot = 0, maxTyp = 0, totDiffs = [];
  for (const f of sample) {
    const d = load(f), a = score(d, f), b = score(xform(d, fn), f);
    if (a.length !== b.length) continue;
    sameSplit++;
    // 세대 순서는 위치 정렬에 따라 바뀔 수 있다 — 유형·점수로 짝짓는다(같은 다중집합인지)
    const ta = a.map((r) => r.score.total).sort((p, q) => p - q), tb = b.map((r) => r.score.total).sort((p, q) => p - q);
    const ya = a.map((r) => r.typicality ? r.typicality.score : 0).sort((p, q) => p - q), yb = b.map((r) => r.typicality ? r.typicality.score : 0).sort((p, q) => p - q);
    for (let i = 0; i < ta.length; i++) { const dt = Math.abs(ta[i] - tb[i]); totDiffs.push(dt); maxTot = Math.max(maxTot, dt); maxTyp = Math.max(maxTyp, Math.abs(ya[i] - yb[i])); units++; }
  }
  totDiffs.sort((p, q) => p - q);
  invRes[k] = { files: sample.length, sameSplit, units, exact: totDiffs.filter((x) => x < 1e-9).length, within1: totDiffs.filter((x) => x <= 1).length, maxTotal: +maxTot.toFixed(2), maxTypicality: +maxTyp.toFixed(2) };
}
console.log("1) 불변성", JSON.stringify(invRes, null, 1));

// 2) 손상 실험 — 거실↔안방 라벨 교환 · 주방 삭제
const dmg = { swap: { n: 0, dropTyp: 0, dTyp: [], dTot: [] }, nokitchen: { n: 0, gated: 0 } };
for (const f of sample) {
  const d = load(f), a = score(d, f);
  // 세대 하나짜리 도면만(짝짓기 단순)
  if (a.length !== 1 || !a[0].typicality) continue;
  const u = E.loadUnits(d, f, {})[0], liv = E.unitOf(u, "living")[0], beds = E.unitOf(u, "bed");
  if (!liv || !beds.length) continue;
  const master = beds.reduce((m, b) => (u.spaces[b].area > u.spaces[m].area ? b : m), beds[0]);
  const la = u.spaces[liv].ann, ma = u.spaces[master].ann;
  const s = JSON.parse(JSON.stringify(d));
  for (const x of s.annotations) { if (x.id === la) x.category_id = 14; else if (x.id === ma) x.category_id = 13; }
  const b = score(s, f);
  if (b.length === 1 && b[0].typicality) { dmg.swap.n++; const dt = b[0].typicality.score - a[0].typicality.score; dmg.swap.dTyp.push(dt); dmg.swap.dTot.push(b[0].score.total - a[0].score.total); if (dt < 0) dmg.swap.dropTyp++; }
  const k = JSON.parse(JSON.stringify(d)); k.annotations = k.annotations.filter((x) => x.category_id !== 15);
  const c = score(k, f); if (c.length) { dmg.nokitchen.n++; if (c.every((r) => r.score.gated)) dmg.nokitchen.gated++; }
}
const mean = (xs) => xs.reduce((p, q) => p + q, 0) / xs.length;
console.log("2) 손상", JSON.stringify({ swap: { n: dmg.swap.n, 근접도하락비율: +(dmg.swap.dropTyp / dmg.swap.n).toFixed(3), 근접도평균변화: +mean(dmg.swap.dTyp).toFixed(2), 총점평균변화: +mean(dmg.swap.dTot).toFixed(2) },
  nokitchen: { n: dmg.nokitchen.n, 필수탈락비율: +(dmg.nokitchen.gated / dmg.nokitchen.n).toFixed(3) } }));

// 3) 민감도 — 판정 기준값을 바꿔 순위(Kendall τ)와 세대 나눔이 얼마나 흔들리는지
const ref = new Map(); const keyOf = (r) => r.unit;
for (const f of sample) for (const r of score(load(f), f)) ref.set(keyOf(r), r);
const variants = { "wall_tol_px=25": { wall_tol_px: 25 }, "wall_tol_px=40": { wall_tol_px: 40 }, "min_contact_px=30": { min_contact_px: 30 }, "min_contact_px=60": { min_contact_px: 60 },
  "duct_area_px=6000": { duct_area_px: 6000 }, "duct_area_px=20000": { duct_area_px: 20000 }, "graph=adjacency": { graph: "adjacency" } };
const sens = {};
for (const [name, p] of Object.entries(variants)) {
  const tot0 = [], tot1 = [], typ0 = [], typ1 = []; let units = 0, matched = 0;
  for (const f of sample) for (const r of score(load(f), f, p)) {
    units++; const o = ref.get(keyOf(r)); if (!o || o.type !== r.type) continue; matched++;
    tot0.push(o.score.total); tot1.push(r.score.total);
    if (o.typicality && r.typicality) { typ0.push(o.typicality.score); typ1.push(r.typicality.score); }
  }
  sens[name] = { 세대수: units, 기준과같은세대: +(matched / ref.size).toFixed(3), tau총점: +kendall(tot0, tot1).toFixed(3), tau근접도: +kendall(typ0, typ1).toFixed(3) };
}
console.log("3) 민감도(기준 세대 " + ref.size + ")", JSON.stringify(sens, null, 1));
