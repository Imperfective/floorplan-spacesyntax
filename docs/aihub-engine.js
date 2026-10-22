/* AI 허브 라벨 평가 엔진 — floorplan_bench/{aihub,evaluate,criteria}.py 의 자바스크립트 판.
 *
 * 브라우저(docs/aihub.html)와 node(tests/test_engine_parity.py) 양쪽에서 돈다.
 * 같은 입력·같은 설정이면 파이썬과 같은 값을 내야 한다 — 고칠 때는 둘을 함께 고친다.
 */
(function (root) {
"use strict";

/* ═════════════════════════════════════ 카테고리 */
const SPACE_CATS = {
  13: ["living", "거실"], 14: ["bed", "침실"], 15: ["kitchen", "주방"], 16: ["entry", "현관"],
  17: ["balcony", "발코니"], 18: ["bath", "화장실"], 19: ["ac", "실외기실"], 20: ["dress", "드레스룸"],
  22: ["etc", "기타"], 1: ["multi", "다목적공간"],
};
const CORE_CATS = { 2: "엘리베이터홀", 3: "계단실", 23: "엘리베이터" };
const STR_CATS = { 9: "door", 10: "window", 11: "wall" };
const OBJ_CATS = { 4: "변기", 5: "세면대", 6: "싱크대", 7: "욕조", 8: "가스레인지" };
const CIRCULATION = ["living", "etc", "multi", "kitchen", "entry"];
const KIND_NAME = Object.fromEntries(Object.values(SPACE_CATS).map(([k, n]) => [k, n]));

/* ═════════════════════════════════════ 변수 (LoadOptions + EvalParams) */
const PARAMS = {
  px_per_m:        { def: null,  label: "축척 고정(px/m)", hint: "비우면 시트의 침실 중앙값으로 추정", group: "읽기" },
  ref_bed_m2:      { def: 9.0,   label: "축척 추정: 침실 중앙값(㎡)", hint: "라벨에 축척이 없어 침실 넓이로 가늠", group: "읽기" },
  wall_tol_px:     { def: 32.0,  label: "벽 두께 허용(px)", hint: "이 거리 안이면 벽 하나 사이로 맞닿은 실", group: "읽기" },
  min_contact_m:   { def: 0.6,   label: "최소 접면(m)", hint: "이보다 짧게 닿으면 맞닿음으로 안 봄(모서리 접촉)", group: "읽기" },
  min_space_ratio: { def: 0.012, label: "샤프트로 뺄 '기타' 크기", hint: "세대 면적 대비 이보다 작은 기타실 제외", group: "읽기" },
  orphan_reach_m:  { def: 2.0,   label: "떨어진 실 붙일 거리(m)", hint: "현관 없는 조각을 이 거리 안 세대에 붙임", group: "읽기" },
  sample_step_px:  { def: 6.0,   label: "경계 표본 간격(px)", hint: "작을수록 정확·느림", group: "읽기" },
  balcony:         { def: "leaf", label: "발코니 연결", hint: "leaf 한 실에만 · all 맞닿은 실 모두 · none 제외", group: "문 추정", options: ["leaf", "all", "none"] },
  include_service: { def: true,  label: "실외기실 포함", hint: "", group: "문 추정" },
  bridge_isolated: { def: true,  label: "고립 조각 자동 연결", hint: "규칙으로 문이 안 생긴 조각을 가장 긴 접면으로 이음", group: "문 추정" },
  overlap_max:     { def: 0.05,  label: "겹침 허용 비율", hint: "작은 실 대비 이보다 많이 겹치면 겹침(F2)", group: "판정" },
  daylight_min_m:  { def: 0.9,   label: "채광 최소 접면(m)", hint: "거실·침실이 외기·발코니에 면해야 하는 길이(F6)", group: "판정" },
  door_window_min_overlap: { def: 0.15, label: "문·창 겹침 비율", hint: "STR 문·창 박스 겹침 판정(F8)", group: "판정" },
};
const defaultParams = () => Object.fromEntries(Object.entries(PARAMS).map(([k, v]) => [k, v.def]));

/* ═════════════════════════════════════ 기하 */
const pts = (flat) => { const o = []; for (let i = 0; i + 1 < flat.length; i += 2) o.push([flat[i], flat[i + 1]]); return o; };
function segDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
function polyDist(p, poly) {
  let m = Infinity;
  for (let i = 0; i < poly.length; i++) { const d = segDist(p, poly[i], poly[(i + 1) % poly.length]); if (d < m) m = d; }
  return m;
}
function inside(p, poly) {
  let c = false; const [x, y] = p;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    if ((y1 > y) !== (y2 > y) && x < (x2 - x1) * (y - y1) / (y2 - y1) + x1) c = !c;
  }
  return c;
}
function boundarySamples(poly, step) {
  const out = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const n = Math.max(1, Math.floor(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let j = 0; j < n; j++) out.push([a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n]);
  }
  return out;
}
function bboxGap(a, b) {
  const dx = Math.max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0);
  const dy = Math.max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0);
  return Math.max(dx, dy);
}
/* 라벨 자리 — ㄱ자 실은 바운딩박스 중심이 실 밖에 떨어진다. 안쪽에서 벽과 가장 먼 점(격자 탐색). */
function labelPoint(poly, bbox) {
  const [x, y, w, h] = bbox, c = [x + w / 2, y + h / 2];
  let best = inside(c, poly) ? c : null, bd = best ? polyDist(c, poly) : -1;
  const n = 14;
  for (let i = 1; i < n; i++) for (let j = 1; j < n; j++) {
    const p = [x + w * i / n, y + h * j / n];
    if (!inside(p, poly)) continue;
    const d = polyDist(p, poly);
    if (d > bd * 1.15) { bd = d; best = p; }   // 중심을 조금 더 선호
  }
  return best || c;
}
const bbOf = (poly) => {
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
  const x0 = Math.min(...xs), y0 = Math.min(...ys);
  return [x0, y0, Math.max(...xs) - x0, Math.max(...ys) - y0];
};
const pairKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
const median = (xs) => { const s = [...xs].sort((a, b) => a - b), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
const fin = (v) => v != null && Number.isFinite(v);

/* ═════════════════════════════════════ 라벨 종류 */
function labelType(data, name = "") {
  const base = name.toUpperCase();
  for (const t of ["SPA", "STR", "OBJ", "OCR"]) if (base.includes(`_${t}_`)) return t;
  const cats = new Set((data.annotations || []).map(a => a.category_id));
  if ([...cats].some(c => SPACE_CATS[c])) return "SPA";
  if ([...cats].some(c => STR_CATS[c])) return "STR";
  if ([...cats].some(c => OBJ_CATS[c])) return "OBJ";
  return "OCR";
}

/* ═════════════════════════════════════ 세대 읽기 */
function contact(pa, pb, bba, bbb, o) {
  if (bboxGap(bba, bbb) > o.wall_tol_px) return [0, null];
  const sa = boundarySamples(pa, o.sample_step_px).filter(p => polyDist(p, pb) <= o.wall_tol_px);
  const sb = boundarySamples(pb, o.sample_step_px).filter(p => polyDist(p, pa) <= o.wall_tol_px);
  if (!sa.length || !sb.length) return [0, null];
  const all = sa.concat(sb);
  const mx = all.reduce((s, p) => s + p[0], 0) / all.length, my = all.reduce((s, p) => s + p[1], 0) / all.length;
  let best = all[0], bd = Infinity;
  for (const p of all) { const d = Math.hypot(p[0] - mx, p[1] - my); if (d < bd) { bd = d; best = p; } }
  return [Math.min(sa.length, sb.length) * o.sample_step_px, best];
}

function loadUnits(data, source, params = {}) {
  const o = Object.assign(defaultParams(), params);
  const raw = [], core = [];
  for (const a of data.annotations || []) {
    const cid = a.category_id;
    if (!a.segmentation || !a.segmentation[0] || !a.segmentation[0].length) continue;
    const poly = pts(a.segmentation[0]);
    if (poly.length < 3) continue;
    const item = { cid, poly, area: +a.area, bbox: a.bbox.slice(0, 4), ann: a.id };
    if (SPACE_CATS[cid]) raw.push(item); else if (CORE_CATS[cid]) core.push(item);
  }
  if (!(o.px_per_m > 0)) {
    const beds = raw.filter(r => SPACE_CATS[r.cid][0] === "bed").map(r => r.area).sort((a, b) => a - b);
    o.px_per_m = beds.length ? Math.sqrt(beds[Math.floor(beds.length / 2)] / o.ref_bed_m2) : 100;
  }
  const n = raw.length, minContact = o.min_contact_m * o.px_per_m;
  const con = new Map(), mids = new Map();   // "i|j" (i<j, 숫자) → 길이
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const [L, mid] = contact(raw[i].poly, raw[j].poly, raw[i].bbox, raw[j].bbox, o);
    if (L >= minContact) { con.set(`${i}|${j}`, L); mids.set(`${i}|${j}`, mid); }
  }
  const adj = Array.from({ length: n }, () => new Set());
  for (const k of con.keys()) { const [i, j] = k.split("|").map(Number); adj[i].add(j); adj[j].add(i); }
  const owner = splitByEntry(raw, adj);

  const groups = new Map();
  for (let i = 0; i < n; i++) { if (!groups.has(owner[i])) groups.set(owner[i], []); groups.get(owner[i]).push(i); }
  // 파이썬 dict 순서: owner를 처음 만난 순서 → 정렬 기준이 같으면 그 순서 유지
  const order = [...groups.values()].sort((g, h) => {
    const gx = Math.min(...g.map(i => raw[i].bbox[0])), hx = Math.min(...h.map(i => raw[i].bbox[0]));
    if (gx !== hx) return gx - hx;
    return Math.min(...g.map(i => raw[i].bbox[1])) - Math.min(...h.map(i => raw[i].bbox[1]));
  });
  const isEntry = (i) => SPACE_CATS[raw[i].cid][0] === "entry";
  const homes = order.filter(g => g.some(isEntry)).map(g => g.slice());
  const homeSet = new Set(order.filter(g => g.some(isEntry)));
  for (const g of order) {
    if (homeSet.has(g) || !homes.length) continue;
    let best = null;
    homes.forEach((h, hi) => {
      let gap = Infinity;
      for (const i of g) for (const j of h) gap = Math.min(gap, bboxGap(raw[i].bbox, raw[j].bbox));
      if (!best || gap < best[0] || (gap === best[0] && hi < best[1])) best = [gap, hi];
    });
    if (best[0] <= o.orphan_reach_m * o.px_per_m) homes[best[1]] = homes[best[1]].concat(g);
  }
  return homes.map((members, gi) => makeUnit(source, gi, members, raw, core, con, mids, o));
}

function splitByEntry(raw, adj) {
  const owner = new Array(raw.length), seen = new Set();
  let compId = 0;
  const isEntry = (i) => SPACE_CATS[raw[i].cid][0] === "entry";
  const cen = (i) => [raw[i].bbox[0] + raw[i].bbox[2] / 2, raw[i].bbox[1] + raw[i].bbox[3] / 2];
  for (let s = 0; s < raw.length; s++) {
    if (seen.has(s)) continue;
    const comp = [], stack = [s]; seen.add(s);
    while (stack.length) {
      const v = stack.pop(); comp.push(v);
      for (const u of adj[v]) if (!seen.has(u)) { seen.add(u); stack.push(u); }
    }
    const entries = comp.filter(isEntry);
    if (entries.length <= 1) { for (const i of comp) owner[i] = compId; compId++; continue; }
    const dist = new Map(comp.map(i => [i, new Map()]));
    for (const e of entries) {
      const d = new Map([[e, 0]]); let q = [e];
      while (q.length) {
        const nq = [];
        for (const v of q) for (const u of adj[v]) if (!d.has(u)) { d.set(u, d.get(v) + 1); nq.push(u); }
        q = nq;
      }
      for (const [i, k] of d) dist.get(i).set(e, k);
    }
    for (const i of comp) {
      let best = null;
      for (const e of entries) {
        const [cx, cy] = cen(i), [ex, ey] = cen(e);
        const key = [dist.get(i).has(e) ? dist.get(i).get(e) : 1e9, Math.hypot(cx - ex, cy - ey)];
        if (!best || key[0] < best[0][0] || (key[0] === best[0][0] && key[1] < best[0][1])) best = [key, e];
      }
      owner[i] = compId + entries.indexOf(best[1]);
    }
    compId += entries.length;
  }
  return owner;
}

function makeUnit(source, gi, members, raw, core, con, mids, o) {
  const total = members.reduce((s, i) => s + raw[i].area, 0);
  const keep = [], dropped = [];
  for (const i of members) {
    if (SPACE_CATS[raw[i].cid][0] === "etc" && raw[i].area < o.min_space_ratio * total) dropped.push(i);
    else keep.push(i);
  }
  const byKind = new Map();
  for (const i of keep) { const k = SPACE_CATS[raw[i].cid][0]; if (!byKind.has(k)) byKind.set(k, []); byKind.get(k).push(i); }
  const sidOf = new Map();
  for (const [kind, idx] of byKind) {
    const s = idx.slice().sort((a, b) => raw[b].area - raw[a].area);
    s.forEach((i, r) => sidOf.set(i, idx.length === 1 ? kind : `${kind}${r + 1}`));
  }
  const spaces = {};
  for (const i of keep) {
    const [kind, kname] = SPACE_CATS[raw[i].cid], sid = sidOf.get(i);
    spaces[sid] = { sid, kind, name: kname + (sid === kind ? "" : sid.slice(kind.length)),
      poly: raw[i].poly, area: raw[i].area, bbox: raw[i].bbox, ann: raw[i].ann,
      centroid: labelPoint(raw[i].poly, raw[i].bbox) };
  }
  const contactMap = new Map(), contactMid = new Map();
  for (const [k, L] of con) {
    const [i, j] = k.split("|").map(Number);
    if (sidOf.has(i) && sidOf.has(j)) {
      const pk = pairKey(sidOf.get(i), sidOf.get(j));
      contactMap.set(pk, L); contactMid.set(pk, mids.get(k));
    }
  }
  const others = members.map(i => ({ poly: raw[i].poly, idx: i })).concat(core.map(c => ({ poly: c.poly, idx: null })));
  const exterior = {};
  for (const i of keep) {
    const near = others.filter(q => q.idx !== i && bboxGap(raw[i].bbox, bbOf(q.poly)) <= o.wall_tol_px);
    const free = boundarySamples(raw[i].poly, o.sample_step_px)
      .filter(p => near.every(q => polyDist(p, q.poly) > o.wall_tol_px)).length;
    exterior[sidOf.get(i)] = free * o.sample_step_px;
  }
  const area = Object.values(spaces).reduce((s, x) => s + x.area, 0);
  return {
    source, index: gi, uid: `${source.replace(/\.json$/i, "")}#${gi}`,
    spaces, contact: contactMap, contactMid, exterior, px_per_m: o.px_per_m, area,
    dropped: dropped.map(i => `${SPACE_CATS[raw[i].cid][1]}(${(raw[i].area / o.px_per_m ** 2).toFixed(1)}㎡)`),
    droppedAnns: dropped.map(i => raw[i].ann),
    options: o,
  };
}

const unitOf = (u, kind) => Object.keys(u.spaces).filter(k => u.spaces[k].kind === kind);
function neighbors(u, sid) {
  const out = [];
  for (const k of u.contact.keys()) { const [a, b] = k.split("|"); if (a === sid) out.push(b); else if (b === sid) out.push(a); }
  return out;
}
const contactOf = (u, a, b) => u.contact.get(pairKey(a, b)) || 0;

/* ═════════════════════════════════════ STR */
function loadStruct(data, source) {
  const out = { source, door: [], window: [], wall: [] };
  for (const a of data.annotations || []) {
    const kind = STR_CATS[a.category_id]; if (!kind) continue;
    const attrs = Object.entries(a.attributes || {}).filter(([k]) => k !== "occluded" && k !== "rotation");
    out[kind].push({ id: a.id, bbox: a.bbox, poly: a.segmentation && a.segmentation[0] ? pts(a.segmentation[0]) : [],
      type: attrs.length ? String(attrs[0][1]) : "" });
  }
  return out;
}
function structChecks(sh, minOverlap = PARAMS.door_window_min_overlap.def) {
  const out = [];
  for (const d of sh.door) for (const w of sh.window) {
    const [ax, ay, aw, ah] = d.bbox, [bx, by, bw, bh] = w.bbox;
    const ix = Math.max(0, Math.min(ax + aw, bx + bw) - Math.max(ax, bx));
    const iy = Math.max(0, Math.min(ay + ah, by + bh) - Math.max(ay, by));
    const small = Math.max(1, Math.min(aw * ah, bw * bh)), r = ix * iy / small;
    if (r > minOverlap) out.push({ id: "F8", level: "error", criterion: "문·창 겹침 없음 (STR)",
      message: `문(${d.type}) #${d.id} 과 창(${w.type}) #${w.id} 겹침 ${(r * 100).toFixed(0)}%`,
      rooms: [], door: d.id, window: w.id });
  }
  return out;
}

/* ═════════════════════════════════════ 문 추정 */
const ONE_OF = {
  bed: ["living", "etc", "multi", "kitchen", "entry"],
  bath: ["dress", "living", "etc", "multi", "entry", "kitchen", "bed"],
  dress: ["bed", "etc", "living", "multi"],
  ac: ["balcony", "bed", "living", "kitchen", "etc"],
};
function reachFrom(adj, starts, blocked = new Set()) {
  const seen = new Set(starts); let q = starts.slice();
  while (q.length) {
    const nq = [];
    for (const v of q) for (const n of adj[v]) if (!seen.has(n) && !blocked.has(n)) { seen.add(n); nq.push(n); }
    q = nq;
  }
  return seen;
}
function permeability(u, p) {
  const sp = u.spaces;
  const nodes = Object.keys(sp).filter(k => !(sp[k].kind === "balcony" && p.balcony === "none") && !(sp[k].kind === "ac" && !p.include_service));
  const adj = Object.fromEntries(nodes.map(k => [k, new Set()]));
  const link = (a, b) => { if (adj[a] && adj[b] && a !== b) { adj[a].add(b); adj[b].add(a); } };
  for (const k of u.contact.keys()) {
    const [a, b] = k.split("|");
    if (CIRCULATION.includes(sp[a].kind) && CIRCULATION.includes(sp[b].kind)) link(a, b);
  }
  for (const k of nodes) {
    const kind = sp[k].kind, nbrs = neighbors(u, k);
    if (ONE_OF[kind]) {
      for (const target of ONE_OF[kind]) {
        const c = nbrs.filter(n => sp[n].kind === target && adj[n]);
        const key = (kind === "bath" && target === "bed") ? (n => -sp[n].area) : (n => -contactOf(u, k, n));
        c.sort((x, y) => key(x) - key(y));   // 안정 정렬 — 파이썬 sort와 같다
        if (c.length) { link(k, c[0]); break; }
      }
    } else if (kind === "balcony" && p.balcony !== "none") {
      const hosts = nbrs.filter(n => ["living", "bed", "kitchen", "etc", "multi"].includes(sp[n].kind));
      if (p.balcony === "all") hosts.forEach(n => link(k, n));
      else if (hosts.length) {
        const ord = { living: 0, kitchen: 1, bed: 2, multi: 3, etc: 4 };
        let best = hosts[0];
        for (const n of hosts.slice(1)) {
          const a = [ord[sp[n].kind], -contactOf(u, k, n)], b = [ord[sp[best].kind], -contactOf(u, k, best)];
          if (a[0] < b[0] || (a[0] === b[0] && a[1] < b[1])) best = n;
        }
        link(k, best);
      } else nbrs.forEach(n => { if (sp[n].kind === "balcony") link(k, n); });
    }
  }
  while (p.bridge_isolated) {
    const reach = reachFrom(adj, unitOf(u, "entry").filter(e => adj[e]));
    const bridges = [];
    for (const key of u.contact.keys()) {
      const [a, b] = key.split("|");
      if (adj[a] && adj[b] && reach.has(a) !== reach.has(b)) bridges.push([contactOf(u, a, b), a, b]);
    }
    if (!reach.size || !bridges.length) break;
    bridges.sort((x, y) => (y[0] - x[0]) || (y[1] < x[1] ? -1 : y[1] > x[1] ? 1 : 0) || (y[2] < x[2] ? -1 : y[2] > x[2] ? 1 : 0));
    link(bridges[0][1], bridges[0][2]);
  }
  return adj;
}

/* ═════════════════════════════════════ 시공 가능성 */
function overlapRatio(a, b, step) {
  const x0 = Math.max(a.bbox[0], b.bbox[0]), y0 = Math.max(a.bbox[1], b.bbox[1]);
  const x1 = Math.min(a.bbox[0] + a.bbox[2], b.bbox[0] + b.bbox[2]), y1 = Math.min(a.bbox[1] + a.bbox[3], b.bbox[1] + b.bbox[3]);
  if (x1 <= x0 || y1 <= y0) return 0;
  let hit = 0;
  for (let y = y0 + step / 2; y < y1; y += step) for (let x = x0 + step / 2; x < x1; x += step)
    if (inside([x, y], a.poly) && inside([x, y], b.poly)) hit++;
  return hit * step * step / Math.min(a.area, b.area);
}
const daylightPx = (u, k) => (u.exterior[k] || 0) +
  neighbors(u, k).filter(n => ["balcony", "ac"].includes(u.spaces[n].kind)).reduce((s, n) => s + contactOf(u, k, n), 0);

const CRIT_NAME = { F1: "필수실 구성", F2: "실 겹침 없음", F3: "출입 불가 실 없음", F4: "침실 경유 동선 없음",
  F5: "주방-화장실 직결 없음", F6: "거실·침실 채광(외기 접면)", F8: "문·창 겹침 없음 (STR)" };

function feasibility(u, adj, p) {
  const sp = u.spaces, issues = [];
  const add = (id, level, message, rooms = []) => issues.push({ id, level, criterion: CRIT_NAME[id], message, rooms });
  const need = { entry: [1, 1], living: [1, 9], kitchen: [1, 9], bed: [1, 9], bath: [1, 9] };
  for (const [kind, [lo, hi]] of Object.entries(need)) {
    const n = unitOf(u, kind).length;
    if (n < lo || n > hi) add("F1", "error", `${KIND_NAME[kind]} ${n}개 (허용 ${lo}~${hi})`);
  }
  const keys = Object.keys(sp), step = u.px_per_m * 0.1;
  for (let i = 0; i < keys.length; i++) for (let j = i + 1; j < keys.length; j++) {
    const r = overlapRatio(sp[keys[i]], sp[keys[j]], step);
    if (r > p.overlap_max) add("F2", "error", `${sp[keys[i]].name}·${sp[keys[j]].name} ${(r * 100).toFixed(0)}% 겹침`, [keys[i], keys[j]]);
  }
  const entries = unitOf(u, "entry").filter(e => adj[e]);
  const reach = reachFrom(adj, entries);
  const lost = Object.keys(adj).filter(k => !reach.has(k));
  const main = lost.filter(k => ["living", "bed", "kitchen", "bath", "dress", "entry"].includes(sp[k].kind));
  const minor = lost.filter(k => !main.includes(k));
  if (main.length) add("F3", "error", "현관에서 닿지 않는 실: " + main.map(k => sp[k].name).join(", "), main);
  if (minor.length) add("F3", "info", "고립된 부속 공간(샤프트·외부 요소로 간주): " + minor.map(k => sp[k].name).join(", "), minor);
  if (entries.length) for (const b of unitOf(u, "bed")) {
    if (!reach.has(b)) continue;
    const blocked = new Set(unitOf(u, "bed").filter(x => x !== b));
    if (!reachFrom(adj, entries, blocked).has(b)) add("F4", "warn", `${sp[b].name}은(는) 다른 침실을 거쳐야 들어감`, [b]);
  }
  for (const k of unitOf(u, "kitchen")) for (const n of adj[k] || [])
    if (sp[n].kind === "bath") add("F5", "warn", `${sp[k].name}에서 ${sp[n].name}로 바로 출입`, [k, n]);
  const minExt = p.daylight_min_m * u.px_per_m;
  for (const [k, s] of Object.entries(sp)) {
    if (s.kind !== "living" && s.kind !== "bed") continue;
    if (daylightPx(u, k) < minExt) add("F6", "warn", `${s.name}이(가) 외기·발코니에 면하지 않음(창 둘 자리 없음)`, [k]);
  }
  return issues;
}

/* ═════════════════════════════════════ 공간구문 (spacesyntax.analyze_graph) */
const CARRIER = "__carrier__";
function syntaxGraph(u, adj) {
  const nodes = [CARRIER, ...Object.keys(adj)];
  const g = Object.fromEntries(Object.entries(adj).map(([k, v]) => [k, new Set(v)]));
  g[CARRIER] = new Set();
  for (const e of unitOf(u, "entry")) if (g[e]) { g[CARRIER].add(e); g[e].add(CARRIER); }
  return { nodes, adj: g };
}
function bfs(adj, src) {
  const d = new Map([[src, 0]]); let q = [src];
  while (q.length) { const nq = []; for (const v of q) for (const u of adj[v]) if (!d.has(u)) { d.set(u, d.get(v) + 1); nq.push(u); } q = nq; }
  return d;
}
function diamond(k) { return k < 4 ? NaN : 2 * (k * (Math.log2((k + 2) / 3) - 1) + 1) / ((k - 1) * (k - 2)); }
function betweenness(nodes, adj) {
  const cb = Object.fromEntries(nodes.map(v => [v, 0]));
  for (const s of nodes) {
    const stack = [], preds = Object.fromEntries(nodes.map(v => [v, []]));
    const sigma = Object.fromEntries(nodes.map(v => [v, 0])), dist = Object.fromEntries(nodes.map(v => [v, -1]));
    sigma[s] = 1; dist[s] = 0; const q = [s];
    while (q.length) {
      const v = q.shift(); stack.push(v);
      for (const w of adj[v]) {
        if (dist[w] < 0) { dist[w] = dist[v] + 1; q.push(w); }
        if (dist[w] === dist[v] + 1) { sigma[w] += sigma[v]; preds[w].push(v); }
      }
    }
    const delta = Object.fromEntries(nodes.map(v => [v, 0]));
    while (stack.length) { const w = stack.pop(); for (const v of preds[w]) delta[v] += sigma[v] / sigma[w] * (1 + delta[w]); if (w !== s) cb[w] += delta[w]; }
  }
  const n = nodes.length, norm = n > 2 ? (n - 1) * (n - 2) : 1;
  return Object.fromEntries(Object.entries(cb).map(([k, v]) => [k, v / norm]));
}
function r2(xs, ys) {
  const n = xs.length; if (n < 3) return NaN;
  const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; syy += (ys[i] - my) ** 2; }
  return sxx <= 0 || syy <= 0 ? NaN : sxy * sxy / (sxx * syy);
}
function analyzeGraph(G) {
  const k = G.nodes.length, dk = diamond(k), choice = betweenness(G.nodes, G.adj);
  const cd = G.adj[CARRIER] ? bfs(G.adj, CARRIER) : new Map();
  const nodes = {};
  for (const v of G.nodes) {
    const d = bfs(G.adj, v), reach = [...d.entries()].filter(([u]) => u !== v).map(([, x]) => x);
    const td = reach.reduce((a, b) => a + b, 0), md = k > 1 ? td / (k - 1) : NaN;
    const ra = k > 2 ? 2 * (md - 1) / (k - 2) : NaN, rra = Number.isFinite(dk) && dk ? ra / dk : NaN;
    nodes[v] = { connectivity: G.adj[v].size, total_depth: td, mean_depth: md, RA: ra, RRA: rra,
      integration: rra > 0 ? 1 / rra : NaN,
      control_value: [...G.adj[v]].reduce((s, u) => s + (G.adj[u].size ? 1 / G.adj[u].size : 0), 0),
      choice: choice[v], step_depth_from_carrier: cd.has(v) ? cd.get(v) : null, disconnected: reach.length < k - 1 };
  }
  const fins = G.nodes.filter(v => Number.isFinite(nodes[v].integration));
  const glob = {
    node_count: k, edge_count: G.nodes.reduce((s, v) => s + G.adj[v].size, 0) / 2, diamond_value: dk,
    mean_depth_system: G.nodes.reduce((s, v) => s + nodes[v].mean_depth, 0) / k,
    mean_integration: fins.length ? fins.reduce((s, v) => s + nodes[v].integration, 0) / fins.length : NaN,
    max_depth_from_carrier: cd.size ? Math.max(...cd.values()) : null,
    intelligibility: r2(fins.map(v => nodes[v].connectivity), fins.map(v => nodes[v].integration)),
  };
  return { nodes, global: glob };
}

/* ═════════════════════════════════════ 특징 · 정답지 */
const FEATURES = {
  n_bed: "침실 수", n_bath: "화장실 수", n_nodes: "실 수(그래프 노드)",
  r_living: "거실 면적비", r_bed: "침실 면적비", r_kitchen: "주방 면적비", r_bath: "화장실 면적비",
  r_entry: "현관 면적비", r_balcony: "발코니 면적비", r_master: "안방/거실 면적비",
  mean_depth: "전체 평균 깊이", max_depth: "외부로부터 최대 깊이", living_depth: "거실 깊이(외부→)",
  bed_depth: "침실 평균 깊이", living_int_rank: "거실 통합도 순위(1=가장 통합)", living_RRA: "거실 RRA",
  ringiness: "고리성(순환 동선)",
};
function features(u, adj) {
  const G = syntaxGraph(u, adj), res = analyzeGraph(G), nodes = res.nodes, glob = res.global;
  const tot = u.area, by = (kind) => unitOf(u, kind).reduce((s, k) => s + u.spaces[k].area, 0);
  const d0 = bfs(G.adj, CARRIER), beds = unitOf(u, "bed"), living = unitOf(u, "living");
  const ranked = Object.keys(adj).filter(k => Number.isFinite(nodes[k].integration)).sort((a, b) => nodes[b].integration - nodes[a].integration);
  const E = glob.edge_count, V = glob.node_count;
  const bd = beds.filter(b => d0.has(b)).map(b => d0.get(b));
  const f = {
    n_bed: beds.length, n_bath: unitOf(u, "bath").length, n_nodes: Object.keys(adj).length,
    r_living: by("living") / tot, r_bed: by("bed") / tot, r_kitchen: by("kitchen") / tot,
    r_bath: by("bath") / tot, r_entry: by("entry") / tot, r_balcony: by("balcony") / tot,
    r_master: beds.length && living.length && by("living") ? Math.max(...beds.map(b => u.spaces[b].area)) / by("living") : null,
    mean_depth: glob.mean_depth_system, max_depth: glob.max_depth_from_carrier,
    living_depth: living.length && d0.has(living[0]) ? d0.get(living[0]) : null,
    bed_depth: bd.length ? bd.reduce((a, b) => a + b, 0) / bd.length : null,
    living_int_rank: living.length && ranked.includes(living[0]) ? ranked.indexOf(living[0]) + 1 : null,
    living_RRA: living.length ? nodes[living[0]].RRA : null,
    ringiness: (E - V + 1) / Math.max(1, 2 * V - 5),
  };
  return { f, res, ranked };
}
const typeKey = (u) => `${unitOf(u, "bed").length}R${unitOf(u, "bath").length}B`;

function buildBaseline(rows) {
  const summarize = (rs) => {
    const out = {};
    for (const k of Object.keys(FEATURES)) {
      const xs = rs.map(r => r[k]).filter(fin).sort((a, b) => a - b);
      if (xs.length < 3) continue;
      const med = median(xs), mad = median(xs.map(x => Math.abs(x - med))) * 1.4826;
      const q1 = xs[Math.floor(xs.length / 4)], q3 = xs[Math.floor(3 * xs.length / 4)];
      out[k] = { median: med, scale: Math.max(mad, (q3 - q1) / 1.349, 0.05 * Math.abs(med), 1e-6), n: xs.length, min: xs[0], max: xs[xs.length - 1] };
    }
    return out;
  };
  const byType = {};
  for (const r of rows) (byType[r.type] = byType[r.type] || []).push(r);
  const types = {};
  for (const [t, rs] of Object.entries(byType)) if (rs.length >= 5) types[t] = { n: rs.length, features: summarize(rs) };
  const counts = Object.fromEntries(Object.entries(byType).map(([t, rs]) => [t, rs.length]).sort((a, b) => b[1] - a[1]));
  return { n_units: rows.length, all: summarize(rows), types, type_counts: counts };
}
function typicality(f, ttype, base, skip = ["n_bed", "n_bath"]) {
  const tref = base.types && base.types[ttype];
  const ref = (tref && tref.features) || base.all, per = {};
  for (const [k, b] of Object.entries(ref)) {
    if (skip.includes(k) || !fin(f[k])) continue;
    const z = (f[k] - b.median) / Math.max(b.scale || 0, 1e-3);
    per[k] = { value: f[k], median: b.median, z, score: Math.max(0, 100 * (1 - Math.abs(z) / 3)) };
  }
  const vs = Object.values(per);
  return { reference: tref ? "type:" + ttype : "all", score: vs.length ? vs.reduce((s, x) => s + x.score, 0) / vs.length : NaN, features: per };
}

/* ═════════════════════════════════════ 조건 (criteria.py) */
const MEASURES = {
  missing_required:  { label: "필수실 누락 수", scope: "global", span: 1, hint: "현관 1·거실·주방·침실·화장실 중 빠진 것 (F1)" },
  overlap_pairs:     { label: "겹친 실 쌍", scope: "global", span: 1, hint: "넓이가 겹치는 실 쌍 (F2)" },
  unreachable_rooms: { label: "출입 불가 주요실", scope: "global", span: 1, hint: "현관에서 닿지 않는 거실·침실·주방·화장실·드레스룸 (F3)" },
  bed_via_bed:       { label: "침실 경유 침실", scope: "global", span: 1, hint: "다른 침실을 거쳐야만 들어가는 침실 (F4)" },
  kitchen_bath:      { label: "주방-화장실 직결", scope: "global", span: 1, hint: "주방에서 바로 화장실로 (F5)" },
  unlit_rooms:       { label: "채광 불가 거실·침실", scope: "global", span: 1, hint: "외기·발코니에 면하지 않은 거실·침실 (F6)" },
  door_window_overlaps: { label: "문·창 겹침", scope: "global", span: 1, hint: "STR 라벨에서 문과 창이 겹친 곳 (F8). SPA만 있으면 건너뜀" },
  n_bed:             { label: "침실 수", scope: "global", span: 2, hint: "" },
  n_bath:            { label: "화장실 수", scope: "global", span: 1, hint: "" },
  n_spaces:          { label: "실 수", scope: "global", span: 4, hint: "그래프 노드 수(외부 제외)" },
  mean_depth_system: { label: "시스템 평균깊이", scope: "global", span: 1.6, hint: "모든 실 쌍의 평균 이동 횟수. 낮을수록 얕다." },
  max_depth_from_carrier: { label: "외부→최대깊이", scope: "global", span: 3, hint: "외부에서 가장 깊은 실까지 문을 몇 번 지나는가." },
  mean_integration:  { label: "평균 통합도", scope: "global", span: 1.5, hint: "" },
  intelligibility:   { label: "명료성 r²", scope: "global", span: .6, hint: "연결도와 통합도의 상관. 길찾기 쉬움." },
  ringiness:         { label: "고리성", scope: "global", span: .2, hint: "순환 동선의 비율. 0이면 나무 구조." },
  typicality:        { label: "정답지 근접도", scope: "global", span: 40, hint: "AI 허브 실제 도면 분포 대비 0~100. 정답지를 불러와야 계산된다." },
  area_ratio:        { label: "세대 대비 면적비", scope: "room", span: .05, hint: "축척 무관" },
  est_m2:            { label: "면적(㎡, 추정)", scope: "room", span: 4, hint: "축척 추정치 — 참고용" },
  aspect:            { label: "장단변비", scope: "room", span: 1.5, hint: "바운딩박스 긴 변 / 짧은 변" },
  fill:              { label: "충전율", scope: "room", span: .25, hint: "실 넓이 / 바운딩박스 넓이. 낮으면 많이 꺾인 형태" },
  daylight_m:        { label: "외기·발코니 접면(m)", scope: "room", span: 2, hint: "창을 둘 수 있는 길이" },
  step_depth:        { label: "외부→깊이", scope: "room", span: 3, hint: "외부에서 이 실까지 문을 몇 번" },
  integration:       { label: "통합도", scope: "room", span: 2, hint: "1/RRA. 클수록 중심" },
  integration_rank:  { label: "통합도 순위", scope: "room", span: 4, hint: "1이면 가장 통합적" },
  RRA:               { label: "RRA", scope: "room", span: .5, hint: "작을수록 통합적" },
  mean_depth:        { label: "평균깊이", scope: "room", span: 1.2, hint: "" },
  connectivity:      { label: "연결도", scope: "room", span: 3, hint: "이 실에 난 문의 수(추정)" },
  control_value:     { label: "제어값", scope: "room", span: 1.2, hint: "" },
  choice:            { label: "선택도", scope: "room", span: .3, hint: "최단 경로 통과 빈도" },
};
const TARGETS = { living: "거실", bed: "침실(모두)", master: "안방(가장 큰 침실)", kitchen: "주방", entry: "현관",
  bath: "화장실", balcony: "발코니", dress: "드레스룸", ac: "실외기실", etc: "기타", multi: "다목적공간" };
const EFFECTS = { weight: "가중 평균", penalty: "감점", gate: "필수(탈락 시 0점)" };
const MODES = { range: "범위(최선↔최악)", target: "목표값 ± 허용", pass: "합격선(맞으면 1)" };

const PRESETS = {
  "시공가능성 + 공간구문": `@missing_required    <= 0          as=gate         # 필수실(현관·거실·주방·침실·화장실)
@overlap_pairs       <= 0          as=penalty:25   # 실끼리 겹치면 지을 수 없다
@unreachable_rooms   <= 0          as=penalty:25   # 현관에서 닿지 않는 주요실
@door_window_overlaps <= 0         as=penalty:25   # 문과 창이 겹침(STR)
@bed_via_bed         <= 0          as=penalty:5    # 침실을 거쳐 들어가는 침실
@kitchen_bath        <= 0          as=penalty:5    # 주방에서 바로 화장실
@unlit_rooms         <= 0          as=penalty:5    # 창 둘 자리 없는 거실·침실
bed.aspect           <= 2.5        as=penalty:5    # 지나치게 길쭉한 침실
bed.fill             >= 0.6        as=penalty:5    # 지나치게 꺾인 침실
living.integration_rank <= 1 .. 4  w=2             # 거실이 가장 통합된 공간
entry.step_depth     <= 1 .. 3     w=1             # 현관은 외부에서 바로
master.step_depth    == 3 ± 1.5    w=1.5           # 안방은 현관에서 물러나게
@typicality          >= 90 .. 40   w=3             # 정답지(AI 허브) 분포에 가까울수록
`,
  "시공가능성만": `@missing_required    <= 0          as=gate
@overlap_pairs       <= 0          as=gate
@unreachable_rooms   <= 0          as=gate
@door_window_overlaps <= 0         as=gate
@bed_via_bed         <= 0          as=penalty:10
@kitchen_bath        <= 0          as=penalty:10
@unlit_rooms         <= 0          as=penalty:10
`,
  "정답지 근접도 중심": `@missing_required    <= 0          as=gate
@unreachable_rooms   <= 0          as=gate
@typicality          >= 95 .. 50   w=5
living.area_ratio    >= 0.22 .. 0.12 w=1
master.daylight_m    >= 3 .. 0.5   w=1
`,
};

const LINE = /^([A-Za-z0-9_@]+)\s*\.?\s*([A-Za-z0-9_]*)\s*(<=|>=|==)\s*(-?[\d.]+)\s*(?:(\.\.|±|\+-)\s*(-?[\d.]+))?((?:\s+[a-z]+\s*=\s*[\w.:]+)*)\s*$/;
function parseDSL(text) {
  const out = [], errors = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const ln = i + 1;
    let why = raw.includes("#") ? raw.split("#").slice(1).join("#").trim() : "";
    let body = raw.split("#")[0].trim(), enabled = true;
    if (!body && raw.trimStart().startsWith("#!")) { body = raw.trimStart().slice(2).split("#")[0].trim(); enabled = false; why = ""; }
    if (!body) return;
    const m = body.match(LINE);
    if (!m) { errors.push(`${ln}행: 해석 불가 — '${raw.trim()}'`); return; }
    let [, tgt, ms, op, v, , v2, opts] = m;
    v = parseFloat(v); v2 = v2 != null ? parseFloat(v2) : null;
    if (tgt.startsWith("@")) { ms = ms || tgt.slice(1); tgt = "@"; }
    const meta = MEASURES[ms];
    if (!meta) { errors.push(`${ln}행: 알 수 없는 지표 '${ms}'`); return; }
    if (meta.scope === "room" && tgt === "@") { errors.push(`${ln}행: ${ms}는 실 단위 지표입니다 (예: bed.${ms})`); return; }
    if (meta.scope === "global" && tgt !== "@") { errors.push(`${ln}행: ${ms}는 전역 지표입니다 (@${ms})`); return; }
    if (meta.scope === "room" && !TARGETS[tgt]) { errors.push(`${ln}행: 알 수 없는 대상 '${tgt}' (${Object.keys(TARGETS).join(", ")})`); return; }
    const o = Object.fromEntries([...(opts || "").matchAll(/([a-z]+)\s*=\s*([\w.:]+)/g)].map(x => [x[1], x[2]]));
    let eff = o.as || "weight", pen = 0;
    if (eff.startsWith("penalty")) { pen = eff.includes(":") ? parseFloat(eff.split(":")[1]) : 10; eff = "penalty"; }
    if (!EFFECTS[eff]) { errors.push(`${ln}행: 반영방식은 weight · penalty:점수 · gate 중 하나`); return; }
    const c = { measure: ms, scope: meta.scope, room: tgt === "@" ? null : tgt, effect: eff, penalty: pen,
      weight: parseFloat(o.w || 1), agg: o.agg || "worst", enabled, why: why || meta.hint };
    if (op === "==") Object.assign(c, { mode: "target", target: v, tol: v2 != null ? v2 : meta.span / 3 });
    else if (v2 == null && eff !== "weight") Object.assign(c, { mode: "pass", op, value: v });
    else Object.assign(c, { mode: "range", best: v, worst: v2 != null ? v2 : (op === "<=" ? v + meta.span : v - meta.span) });
    out.push(c);
  });
  return { criteria: out, errors };
}
const g = (x) => (x == null ? "" : String(+(+x).toPrecision(6)));
function toDSL(cs) {
  return cs.map(c => {
    const t = c.scope === "room" ? `${c.room}.${c.measure}` : `@${c.measure}`;
    let body = c.mode === "target" ? `${t} == ${g(c.target)} ± ${g(c.tol)}`
      : c.mode === "pass" ? `${t} ${c.op} ${g(c.value)}`
      : `${t} ${c.worst > c.best ? "<=" : ">="} ${g(c.best)} .. ${g(c.worst)}`;
    if (c.effect === "weight" && c.weight !== 1) body += ` w=${g(c.weight)}`;
    if (c.effect === "penalty") body += ` as=penalty:${g(c.penalty)}`;
    if (c.effect === "gate") body += " as=gate";
    if (c.agg && c.agg !== "worst") body += ` agg=${c.agg}`;
    let line = (c.enabled ? "" : "#! ") + body;
    if (c.why && c.enabled) line += `   # ${c.why}`;
    return line;
  }).join("\n");
}
const clamp01 = (x) => Math.max(0, Math.min(1, x));
function scoreValue(c, v) {
  if (!fin(v)) return null;
  if (c.mode === "target") return clamp01(1 - Math.abs(v - c.target) / Math.max(c.tol || 0, 1e-9));
  if (c.mode === "pass") return (c.op === "<=" ? v <= c.value : v >= c.value) ? 1 : 0;
  return clamp01((v - c.worst) / ((c.best - c.worst) || 1e-9));
}
function roomIds(target, rooms) {
  if (target === "master") {
    const beds = Object.keys(rooms).filter(k => rooms[k].kind === "bed");
    if (!beds.length) return [];
    let b = beds[0]; for (const k of beds) if (rooms[k].area_ratio > rooms[b].area_ratio) b = k;
    return [b];
  }
  return Object.keys(rooms).filter(k => rooms[k].kind === target);
}
function scoreCriterion(c, m) {
  if (c.scope === "global") { const v = m.global[c.measure]; return { value: v, score: scoreValue(c, v), room: null }; }
  const ids = roomIds(c.room, m.rooms);
  const sc = ids.map(k => [k, m.rooms[k][c.measure]]).map(([k, v]) => [k, v, scoreValue(c, v)]).filter(x => x[2] != null);
  if (!sc.length) return { value: null, score: null, room: null, note: ids.length ? "값 없음" : "해당 실 없음" };
  if (c.agg === "mean") return { value: sc.reduce((s, x) => s + x[1], 0) / sc.length, score: sc.reduce((s, x) => s + x[2], 0) / sc.length, room: null };
  let w = sc[0]; for (const x of sc) if (x[2] < w[2]) w = x;
  return { value: w[1], score: w[2], room: w[0] };
}
function grade(t) {
  for (const [gr, lim] of [["A+", 95], ["A", 90], ["B+", 85], ["B", 80], ["C+", 70], ["C", 60], ["D", 45]]) if (t >= lim) return gr;
  return "F";
}
function scoreAll(cs, m) {
  const rows = cs.filter(c => c.enabled).map(c => ({ criterion: c, ...scoreCriterion(c, m) }));
  const w = rows.filter(r => r.criterion.effect === "weight" && r.score != null);
  const ws = w.reduce((s, r) => s + r.criterion.weight, 0);
  const base = ws ? w.reduce((s, r) => s + r.criterion.weight * r.score, 0) / ws * 100 : 100;
  let penalty = 0, gated = 0;
  for (const r of rows) {
    if (r.score == null) continue;
    if (r.criterion.effect === "penalty") { r.deduct = r.criterion.penalty * (1 - r.score); penalty += r.deduct; }
    else if (r.criterion.effect === "gate" && r.score < 1) { r.gated = true; gated++; }
    else if (r.criterion.effect === "weight") r.share = ws ? r.criterion.weight / ws * 100 : 0;
  }
  const total = gated ? 0 : Math.max(0, base - penalty);
  return { base, penalty, gated, total, grade: grade(total), rows, skipped: rows.filter(r => r.score == null).length };
}

/* ═════════════════════════════════════ 지표표 + 종합 */
function measures(u, adj, issues, res, f, ranked, typ, dwo = null) {
  const count = (id) => issues.filter(i => i.id === id && i.level !== "info").length;
  const nodes = res.nodes, glob = res.global;
  const gm = {
    missing_required: count("F1"), overlap_pairs: count("F2"),
    unreachable_rooms: issues.filter(i => i.id === "F3" && i.level === "error").reduce((s, i) => s + i.rooms.length, 0),
    bed_via_bed: count("F4"), kitchen_bath: count("F5"), unlit_rooms: count("F6"), door_window_overlaps: dwo,
    n_bed: f.n_bed, n_bath: f.n_bath, n_spaces: Object.keys(adj).length,
    mean_depth_system: glob.mean_depth_system, max_depth_from_carrier: glob.max_depth_from_carrier,
    mean_integration: glob.mean_integration, intelligibility: glob.intelligibility, ringiness: f.ringiness,
    typicality: typ ? typ.score : null,
  };
  const rooms = {};
  for (const [k, s] of Object.entries(u.spaces)) {
    const w = s.bbox[2], h = s.bbox[3], n = nodes[k];
    rooms[k] = { name: s.name, kind: s.kind, area_ratio: s.area / u.area, est_m2: s.area / u.px_per_m ** 2,
      aspect: Math.max(w, h) / Math.max(1, Math.min(w, h)), fill: s.area / Math.max(1, w * h),
      daylight_m: daylightPx(u, k) / u.px_per_m,
      step_depth: n ? n.step_depth_from_carrier : null, integration: n ? n.integration : null,
      integration_rank: ranked.includes(k) ? ranked.indexOf(k) + 1 : null,
      RRA: n ? n.RRA : null, mean_depth: n ? n.mean_depth : null, connectivity: n ? n.connectivity : null,
      control_value: n ? n.control_value : null, choice: n ? n.choice : null };
  }
  return { global: gm, rooms };
}

/* 변수에 달린 부분(문 추정·시공 점검·공간구문) — 조건만 바뀌면 다시 계산하지 않도록 따로 둔다 */
function analyzeUnit(u, params = {}) {
  const p = Object.assign(defaultParams(), params);
  const adj = permeability(u, p), issues = feasibility(u, adj, p);
  const { f, res, ranked } = features(u, adj);
  const doors = [];
  for (const a of Object.keys(adj)) for (const b of adj[a]) if (a < b) doors.push([a, b]);
  doors.sort((x, y) => (x[0] + "|" + x[1]).localeCompare(y[0] + "|" + y[1]));
  return { adj, issues, f, res, ranked, doors };
}
function scoreUnit(u, A, criteria, baseline = null) {
  const typ = baseline ? typicality(A.f, typeKey(u), baseline) : null;
  const m = measures(u, A.adj, A.issues, A.res, A.f, A.ranked, typ);
  const sc = scoreAll(criteria, m);
  return { unit: u.uid, type: typeKey(u), adj: A.adj, doors: A.doors, issues: A.issues, features: A.f, typicality: typ,
    measures: m, score: sc, syntax: A.res, feasibility: { pass: !A.issues.some(i => i.level === "error"),
      errors: A.issues.filter(i => i.level === "error").length, warnings: A.issues.filter(i => i.level === "warn").length } };
}
function evaluate(u, criteria, params = {}, baseline = null) {
  return scoreUnit(u, analyzeUnit(u, params), criteria, baseline);
}

/* 저장용 요약 — 조건과 무관한 부분(지표·특징·점검 결과)만. 구조화 복제 가능한 평범한 객체.
   조건이 바뀌면 원본을 다시 읽지 않고 이 요약으로 다시 채점한다(scoreCached). */
function summarizeUnit(u, A) {
  const m = measures(u, A.adj, A.issues, A.res, A.f, A.ranked, null);
  return { uid: u.uid, type: typeKey(u), features: A.f, measures: m,
    pass: !A.issues.some(i => i.level === "error"),
    issueCounts: Object.fromEntries(ISSUE_IDS.map(id => [id, A.issues.filter(i => i.id === id && i.level !== "info").length])) };
}
function scoreCached(s, criteria, baseline = null) {
  const typ = baseline ? typicality(s.features, s.type, baseline) : null;
  const m = { global: Object.assign({}, s.measures.global, { typicality: typ ? typ.score : null }), rooms: s.measures.rooms };
  return { unit: s.uid, type: s.type, measures: m, score: scoreAll(criteria, m), features: s.features, typicality: typ,
    feasibility: { pass: s.pass }, issueCounts: s.issueCounts, cached: true };
}

/* ═════════════════════════════════════ 통계 집계 (floorplan_bench/stats.py 와 같은 형식) */
const ISSUE_IDS = ["F1", "F2", "F3", "F4", "F5", "F6", "F8"];
const GRADES = ["A+", "A", "B+", "B", "C+", "C", "D", "F"];

/* 세대 결과 → 통계에 남길 한 행. 그림·폴리곤은 빼고 점수·지표·조건점수만. */
function statRow(r, file, extra) {
  const issues = r.issueCounts ? Object.assign({}, r.issueCounts)
    : Object.fromEntries(ISSUE_IDS.map(id => [id, r.issues.filter(i => i.id === id && i.level !== "info").length]));
  return { unit: r.unit, file, type: r.type, total: r.score.total, base: r.score.base, penalty: r.score.penalty,
    gated: r.score.gated, grade: r.score.grade, pass: r.feasibility.pass, issues,
    global: Object.fromEntries(Object.entries(r.measures.global).map(([k, v]) => [k, fin(v) ? v : null])),
    crit: r.score.rows.map(x => x.score), ...(extra || {}) };
}
function describe(xs) {
  const v = xs.filter(fin);
  if (!v.length) return { n: 0, mean: null, median: null, sd: null, min: null, max: null };
  const n = v.length, mean = v.reduce((a, b) => a + b, 0) / n;
  const sd = n > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : null;
  return { n, mean, median: median(v), sd, min: Math.min(...v), max: Math.max(...v) };
}
function aggregate(rows, config, extra = {}) {
  const enabled = config.criteria.filter(c => c.enabled !== false);
  const totals = rows.map(r => r.total);
  const hist = Array.from({ length: 10 }, (_, i) => ({ lo: i * 10, hi: i * 10 + 10, n: 0 }));
  for (const t of totals) hist[Math.min(9, Math.floor(t / 10))].n++;
  const grades = Object.fromEntries(GRADES.map(gr => [gr, rows.filter(r => r.grade === gr).length]));
  const rate = (k) => rows.length ? rows.filter(k).length / rows.length : null;
  const byType = {};
  for (const r of rows) (byType[r.type] = byType[r.type] || []).push(r);
  const files = {};
  for (const r of rows) files[r.file] = (files[r.file] || 0) + 1;
  return {
    kind: "aihub-stats", version: 1, created: extra.created || new Date().toISOString(),
    name: extra.name || "", memo: extra.memo || "",
    config: { params: config.params || {}, criteria: config.criteria, dsl: toDSL(config.criteria) },
    baseline: extra.baseline || null,
    summary: {
      n_files: Object.keys(files).length, n_units: rows.length, score: describe(totals), histogram: hist, grades,
      feasibility_pass_rate: rate(r => r.pass), gated_rate: rate(r => r.gated > 0),
      mean_base: describe(rows.map(r => r.base)).mean, mean_penalty: describe(rows.map(r => r.penalty)).mean,
    },
    by_type: Object.entries(byType).map(([type, rs]) => {
      const d = describe(rs.map(r => r.total));
      return { type, n: rs.length, mean: d.mean, median: d.median, min: d.min, max: d.max, pass_rate: rs.filter(r => r.pass).length / rs.length };
    }).sort((a, b) => b.n - a.n || (a.type < b.type ? -1 : 1)),
    criteria: enabled.map((c, i) => {
      const sc = rows.map(r => r.crit[i]).filter(fin);
      return { index: i, dsl: toDSL([c]).split("   #")[0], measure: c.measure, target: c.scope === "room" ? c.room : "@",
        effect: c.effect, n: sc.length, skipped: rows.length - sc.length,
        mean_score: describe(sc).mean, full_rate: sc.length ? sc.filter(x => x >= 1).length / sc.length : null };
    }),
    issues: ISSUE_IDS.map(id => ({ id, name: CRIT_NAME[id], units: rows.filter(r => r.issues[id] > 0).length,
      count: rows.reduce((s, r) => s + (r.issues[id] || 0), 0) })),
    measures: Object.fromEntries(Object.keys(MEASURES).filter(k => MEASURES[k].scope === "global").map(k => [k, describe(rows.map(r => r.global[k]))])),
    units: rows,
  };
}

const API = { SPACE_CATS, CORE_CATS, STR_CATS, OBJ_CATS, KIND_NAME, PARAMS, defaultParams, MEASURES, TARGETS,
  EFFECTS, MODES, PRESETS, FEATURES, CARRIER, labelType, loadUnits, loadStruct, structChecks, permeability,
  feasibility, features, typeKey, buildBaseline, typicality, parseDSL, toDSL, scoreAll, scoreValue, measures,
  evaluate, analyzeUnit, scoreUnit, summarizeUnit, scoreCached, statRow, aggregate, describe, ISSUE_IDS, GRADES, grade, unitOf, neighbors, pts, bbOf };
if (typeof module !== "undefined" && module.exports) module.exports = API; else root.AIHub = API;
})(typeof globalThis !== "undefined" ? globalThis : this);
