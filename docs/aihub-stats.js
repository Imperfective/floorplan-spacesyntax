/* 연구용 통계 — 기술통계 · 검정 · 분포 그림(SVG). 외부 라이브러리 없이 브라우저와 node 양쪽에서 돈다.
 *
 * 검정: Kruskal–Wallis H(동점 보정, ε²) + Dunn 사후검정(Holm), 일원 분산분석 F(η²), Spearman ρ(동점은 평균 순위),
 *       χ² 독립성(Cramér's V), 비율의 Wilson 95% 신뢰구간. p값은 정칙화 불완전 베타·감마 함수로 계산한다.
 * 그림 색: dataviz 기준 팔레트를 검증해 쓴다(scripts/validate_palette.js) —
 *   집단 3개까지 범주색(#2a78d6 · #eb6834 · #1baf7a, all-pairs 통과), 등급 묶음 4단 순서색(파랑 700/550/400/250, ordinal 통과),
 *   상관은 빨강 ↔ 회색 ↔ 파랑 발산색(OKLab 보간).
 */
(function (root) {
"use strict";
const fin = (v) => typeof v === "number" && Number.isFinite(v);
const clean = (xs) => xs.filter(fin);
const sum = (xs) => { let s = 0; for (const x of xs) s += x; return s; };

/* ═════════════ 특수 함수 */
function gammaln(x) {
  const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let y = x, tmp = x + 5.5; tmp -= (x + 0.5) * Math.log(tmp);
  let ser = 1.000000000190015; for (const ci of c) ser += ci / ++y;
  return -tmp + Math.log(2.5066282746310005 * ser / x);
}
function betacf(a, b, x) {
  const FPMIN = 1e-300; const qab = a + b, qap = a + 1, qam = a - 1;
  let c = 1, d = 1 - qab * x / qap; if (Math.abs(d) < FPMIN) d = FPMIN; d = 1 / d; let h = d;
  for (let m = 1; m <= 500; m++) {
    const m2 = 2 * m;
    let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN; c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN; d = 1 / d; h *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN; c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN; d = 1 / d;
    const del = d * c; h *= del; if (Math.abs(del - 1) < 3e-15) break;
  }
  return h;
}
/* 정칙화 불완전 베타 I_x(a, b) */
function ibeta(x, a, b) {
  if (x <= 0) return 0; if (x >= 1) return 1;
  const bt = Math.exp(gammaln(a + b) - gammaln(a) - gammaln(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? bt * betacf(a, b, x) / a : 1 - bt * betacf(b, a, 1 - x) / b;
}
/* 정칙화 불완전 감마 P(a, x), Q(a, x) */
function gammaP(a, x) {
  if (x <= 0) return 0;
  if (x < a + 1) {
    let ap = a, s = 1 / a, del = s;
    for (let n = 0; n < 1000; n++) { ap++; del *= x / ap; s += del; if (Math.abs(del) < Math.abs(s) * 3e-15) break; }
    return s * Math.exp(-x + a * Math.log(x) - gammaln(a));
  }
  return 1 - gammaQ(a, x);
}
function gammaQ(a, x) {
  if (x <= 0) return 1;
  if (x < a + 1) return 1 - gammaP(a, x);
  const FPMIN = 1e-300; let b = x + 1 - a, c = 1 / FPMIN, d = 1 / b, h = d;
  for (let i = 1; i < 1000; i++) {
    const an = -i * (i - a); b += 2; d = an * d + b; if (Math.abs(d) < FPMIN) d = FPMIN;
    c = b + an / c; if (Math.abs(c) < FPMIN) c = FPMIN; d = 1 / d; const del = d * c; h *= del; if (Math.abs(del - 1) < 3e-15) break;
  }
  return Math.exp(-x + a * Math.log(x) - gammaln(a)) * h;
}
const tCDF = (t, df) => { const p = 0.5 * ibeta(df / (df + t * t), df / 2, 0.5); return t > 0 ? 1 - p : p; };
const tSF2 = (t, df) => ibeta(df / (df + t * t), df / 2, 0.5);            // 양측 p
function tInv(p, df) { let lo = -1e4, hi = 1e4; for (let i = 0; i < 200; i++) { const m = (lo + hi) / 2; if (tCDF(m, df) < p) lo = m; else hi = m; } return (lo + hi) / 2; }
const chi2SF = (x, df) => (x <= 0 ? 1 : gammaQ(df / 2, x / 2));
const fSF = (F, d1, d2) => (F <= 0 ? 1 : ibeta(d2 / (d2 + d1 * F), d2 / 2, d1 / 2));
const normSF2 = (z) => gammaQ(0.5, z * z / 2);                           // 양측 p = 2(1 − Φ(|z|))

/* ═════════════ 기술통계 */
function quantileSorted(s, p) {   // R type 7(엑셀 PERCENTILE.INC와 같음)
  if (!s.length) return NaN;
  const h = (s.length - 1) * p, lo = Math.floor(h), hi = Math.ceil(h);
  return s[lo] + (s[hi] - s[lo]) * (h - lo);
}
function describe(xs) {
  const v = clean(xs), n = v.length;
  if (!n) return { n: 0 };
  const s = v.slice().sort((a, b) => a - b), mean = sum(v) / n;
  let m2 = 0, m3 = 0, m4 = 0;
  for (const x of v) { const d = x - mean, d2 = d * d; m2 += d2; m3 += d2 * d; m4 += d2 * d2; }
  const sd = n > 1 ? Math.sqrt(m2 / (n - 1)) : NaN, se = sd / Math.sqrt(n), tc = n > 1 ? tInv(0.975, n - 1) : NaN;
  const g1 = m2 > 0 ? (m3 / n) / Math.pow(m2 / n, 1.5) : NaN, g2 = m2 > 0 ? (m4 / n) / Math.pow(m2 / n, 2) - 3 : NaN;
  const q1 = quantileSorted(s, 0.25), q3 = quantileSorted(s, 0.75);
  return { n, mean, sd, se, ciLo: mean - tc * se, ciHi: mean + tc * se, median: quantileSorted(s, 0.5), q1, q3, iqr: q3 - q1,
    min: s[0], max: s[n - 1],
    skew: n > 2 ? g1 * Math.sqrt(n * (n - 1)) / (n - 2) : NaN,                      // 표본 왜도 G1(SPSS·엑셀 SKEW와 같음)
    kurt: n > 3 ? ((n + 1) * g2 + 6) * (n - 1) / ((n - 2) * (n - 3)) : NaN,        // 표본 초과 첨도 G2(엑셀 KURT와 같음)
    sorted: s };
}
function wilson(k, n, z = 1.959963984540054) {
  if (!n) return [NaN, NaN];
  const p = k / n, z2 = z * z, den = 1 + z2 / n, c = (p + z2 / (2 * n)) / den, h = z * Math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
/* 동점은 평균 순위. ties = Σ(t³ − t) */
function ranks(v) {
  const idx = v.map((_, i) => i).sort((a, b) => v[a] - v[b]), r = new Array(v.length);
  let ties = 0;
  for (let i = 0; i < idx.length;) {
    let j = i; while (j + 1 < idx.length && v[idx[j + 1]] === v[idx[i]]) j++;
    const avg = (i + j) / 2 + 1; for (let k = i; k <= j; k++) r[idx[k]] = avg;
    const t = j - i + 1; if (t > 1) ties += t * t * t - t; i = j + 1;
  }
  return { r, ties };
}
function pearsonRaw(x, y) {
  const n = x.length, mx = sum(x) / n, my = sum(y) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) { const a = x[i] - mx, b = y[i] - my; sxy += a * b; sxx += a * a; syy += b * b; }
  return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN;
}
function corrTest(r, n) {
  if (!fin(r) || n < 3) return NaN;
  if (Math.abs(r) >= 1) return 0;
  return tSF2(Math.abs(r) * Math.sqrt((n - 2) / (1 - r * r)), n - 2);
}
/* 짝지은 값(둘 다 있는 세대만) */
function pairs(xs, ys) { const a = [], b = []; for (let i = 0; i < xs.length; i++) if (fin(xs[i]) && fin(ys[i])) { a.push(xs[i]); b.push(ys[i]); } return [a, b]; }
function spearman(xs, ys) {
  const [a, b] = pairs(xs, ys), n = a.length;
  if (n < 3) return { rho: NaN, p: NaN, n };
  const rho = pearsonRaw(ranks(a).r, ranks(b).r);
  return { rho, p: corrTest(rho, n), n };
}
/* 상관 행렬 — 변수마다 한 번만 정렬하고, 짝마다 '둘 다 있는 세대'로 순위를 O(n)에 다시 매긴다(짝별 완전 사례) */
function corrMatrix(cols, method = "spearman") {
  const k = cols.length, n = k ? cols[0].length : 0;
  const ok = cols.map((c) => { const m = new Uint8Array(n); for (let i = 0; i < n; i++) m[i] = fin(c[i]) ? 1 : 0; return m; });
  const order = cols.map((c, v) => { const idx = []; for (let i = 0; i < n; i++) if (ok[v][i]) idx.push(i); return idx.sort((a, b) => c[a] - c[b]); });
  const idx = new Int32Array(n), ra = new Float64Array(n), rb = new Float64Array(n);
  const rankOn = (v, keep, out) => {   // keep 안의 세대만 v로 순위(동점 평균)를 out[세대]에
    const c = cols[v], o = order[v]; let m = 0;
    for (let t = 0; t < o.length; t++) if (keep[o[t]]) idx[m++] = o[t];
    for (let i = 0; i < m;) { let j = i; while (j + 1 < m && c[idx[j + 1]] === c[idx[i]]) j++; const avg = (i + j) / 2 + 1; for (let t = i; t <= j; t++) out[idx[t]] = avg; i = j + 1; }
  };
  const M = Array.from({ length: k }, () => new Array(k).fill(null));
  for (let a = 0; a < k; a++) {
    M[a][a] = { r: 1, p: 0, n: ok[a].reduce((s, x) => s + x, 0) };
    for (let b = a + 1; b < k; b++) {
      const keep = new Uint8Array(n); let m = 0;
      for (let i = 0; i < n; i++) if (ok[a][i] && ok[b][i]) { keep[i] = 1; m++; }
      let r = NaN;
      if (m >= 3) {
        const xs = [], ys = [];
        if (method === "spearman") { rankOn(a, keep, ra); rankOn(b, keep, rb); for (let i = 0; i < n; i++) if (keep[i]) { xs.push(ra[i]); ys.push(rb[i]); } }
        else for (let i = 0; i < n; i++) if (keep[i]) { xs.push(cols[a][i]); ys.push(cols[b][i]); }
        r = pearsonRaw(xs, ys);
      }
      M[a][b] = M[b][a] = { r, p: corrTest(r, m), n: m };
    }
  }
  return M;
}
function pearson(xs, ys) { const [a, b] = pairs(xs, ys), n = a.length; const r = n >= 3 ? pearsonRaw(a, b) : NaN; return { r, p: corrTest(r, n), n }; }

/* Holm 보정 */
function holm(ps) {
  const m = ps.length, ord = ps.map((p, i) => [p, i]).sort((x, y) => x[0] - y[0]), out = new Array(m);
  let run = 0;
  ord.forEach(([p, i], k) => { run = Math.max(run, Math.min(1, (m - k) * p)); out[i] = run; });
  return out;
}
/* Kruskal–Wallis H(동점 보정) · ε² = H / (N − 1) · Dunn 사후검정(동점 보정, Holm) */
function kruskal(groups) {
  const gs = groups.map(clean), keep = gs.map((g, i) => [g, i]).filter(([g]) => g.length);
  const all = []; keep.forEach(([g], gi) => g.forEach((x) => all.push([x, gi])));
  const N = all.length, k = keep.length;
  if (k < 2 || N < 3) return null;
  const { r, ties } = ranks(all.map((a) => a[0])), R = new Array(k).fill(0);
  all.forEach((a, i) => { R[a[1]] += r[i]; });
  let H = 12 / (N * (N + 1)) * keep.reduce((s, [g], i) => s + R[i] * R[i] / g.length, 0) - 3 * (N + 1);
  const C = 1 - ties / (N * N * N - N); if (C > 0) H /= C;
  const df = k - 1, meanRank = R.map((s, i) => s / keep[i][0].length);
  const vb = N * (N + 1) / 12 - ties / (12 * (N - 1)), dunn = [];
  for (let i = 0; i < k; i++) for (let j = i + 1; j < k; j++) {
    const z = (meanRank[i] - meanRank[j]) / Math.sqrt(vb * (1 / keep[i][0].length + 1 / keep[j][0].length));
    dunn.push({ a: keep[i][1], b: keep[j][1], z, p: normSF2(Math.abs(z)) });
  }
  const adj = holm(dunn.map((d) => d.p)); dunn.forEach((d, i) => { d.pAdj = adj[i]; });
  return { H, df, p: chi2SF(H, df), eps2: H / (N - 1), N, k, meanRank: Object.fromEntries(keep.map(([, gi], i) => [gi, meanRank[i]])), dunn };
}
/* 일원 분산분석 F · η² */
function anova(groups) {
  const gs = groups.map(clean).filter((g) => g.length), k = gs.length, N = gs.reduce((s, g) => s + g.length, 0);
  if (k < 2 || N <= k) return null;
  const grand = gs.reduce((s, g) => s + sum(g), 0) / N;
  let ssb = 0, ssw = 0;
  for (const g of gs) { const m = sum(g) / g.length; ssb += g.length * (m - grand) ** 2; for (const x of g) ssw += (x - m) ** 2; }
  const d1 = k - 1, d2 = N - k, F = (ssb / d1) / (ssw / d2);
  return { F, d1, d2, p: fSF(F, d1, d2), eta2: ssb / (ssb + ssw), N, k };
}
/* χ² 독립성 검정 · Cramér's V. table[r][c] = 빈도 */
function chi2Indep(table) {
  let T = table.filter((row) => sum(row) > 0);
  const colKeep = T[0] ? T[0].map((_, j) => T.some((row) => row[j] > 0)) : [];
  T = T.map((row) => row.filter((_, j) => colKeep[j]));
  const r = T.length, c = r ? T[0].length : 0;
  if (r < 2 || c < 2) return null;
  const rs = T.map(sum), cs = T[0].map((_, j) => sum(T.map((row) => row[j]))), N = sum(rs);
  let x2 = 0, low = 0;
  for (let i = 0; i < r; i++) for (let j = 0; j < c; j++) { const e = rs[i] * cs[j] / N; if (e < 5) low++; x2 += (T[i][j] - e) ** 2 / e; }
  const df = (r - 1) * (c - 1);
  return { chi2: x2, df, p: chi2SF(x2, df), V: Math.sqrt(x2 / (N * Math.min(r - 1, c - 1))), N, lowShare: low / (r * c) };
}

/* ═════════════ 구간 · 누적분포 */
function niceStep(range, target) {
  const raw = range / Math.max(1, target), mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / mag;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
}
/* 구간: "auto" = Freedman–Diaconis(IQR 기반, 5~60개로 자름), 숫자 = 그 개수 */
function bins(d, mode = "auto", lo = null, hi = null) {
  const s = d.sorted; if (!s || !s.length) return [];
  let a = lo != null ? lo : s[0], b = hi != null ? hi : s[s.length - 1];
  if (b === a) { a -= 0.5; b += 0.5; }
  let k = +mode;
  if (!(k > 0)) { const h = 2 * d.iqr * Math.pow(d.n, -1 / 3); k = h > 0 ? Math.ceil((b - a) / h) : 10; k = Math.max(5, Math.min(60, k)); }
  const w = niceStep(b - a, k), start = Math.floor(a / w) * w, out = [];
  for (let x = start; x <= b + 1e-12 && out.length < 400; x += w) out.push({ lo: +x.toPrecision(12), hi: +(x + w).toPrecision(12), n: 0 });
  let j = 0;
  for (const v of s) { while (j < out.length - 1 && v >= out[j].hi) j++; out[j].n++; }
  return out;
}
function ecdfPoints(sorted, max = 400) {
  const n = sorted.length, out = []; if (!n) return out;
  const step = Math.max(1, Math.floor(n / max));
  for (let i = 0; i < n; i += step) out.push([sorted[i], (i + 1) / n]);
  if (out[out.length - 1][1] !== 1) out.push([sorted[n - 1], 1]);
  return out;
}

/* ═════════════ 표 내보내기 */
const fmtP = (p) => (!fin(p) ? "—" : p < 0.001 ? "< .001" : p.toFixed(3).replace(/^0/, ""));
function exportTable(t, fmt) {
  const cols = t.cols, cell = (row, c) => { const v = row[c.key]; return v == null || (typeof v === "number" && !Number.isFinite(v)) ? "" : c.fmt ? c.fmt(v, row) : String(v); };
  const raw = (row, c) => { const v = row[c.key]; return v == null || (typeof v === "number" && !Number.isFinite(v)) ? "" : typeof v === "number" ? String(+v.toPrecision(8)) : String(v); };
  if (fmt === "csv") {
    const q = (s) => (/[",\r\n]/.test(s) || /^[=+\-@]/.test(s) ? `"${(/^[=+\-@]/.test(s) && !/^-?\d/.test(s) ? "'" : "") + s.replace(/"/g, '""')}"` : s);
    return "\uFEFF" + [cols.map((c) => q(c.label)).join(","), ...t.rows.map((r) => cols.map((c) => q(raw(r, c))).join(","))].join("\r\n");
  }
  if (fmt === "tsv") return [cols.map((c) => c.label).join("\t"), ...t.rows.map((r) => cols.map((c) => cell(r, c)).join("\t"))].join("\n");
  if (fmt === "md") {
    const al = cols.map((c) => (c.num ? "---:" : "---"));
    return [`| ${cols.map((c) => c.label).join(" | ")} |`, `| ${al.join(" | ")} |`, ...t.rows.map((r) => `| ${cols.map((c) => cell(r, c).replace(/\|/g, "\\|")).join(" | ")} |`)].join("\n")
      + (t.note ? `\n\n${t.note}` : "");
  }
  if (fmt === "tex") {
    const tx = (s) => s.replace(/\\/g, "\\textbackslash{}").replace(/([&%$#_{}])/g, "\\$1").replace(/~/g, "\\textasciitilde{}").replace(/\^/g, "\\textasciicircum{}").replace(/</g, "$<$").replace(/>/g, "$>$").replace(/±/g, "$\\pm$");
    return [`\\begin{table}[ht]`, `\\centering`, `\\caption{${tx(t.title || "")}}`, `\\begin{tabular}{${cols.map((c) => (c.num ? "r" : "l")).join("")}}`, `\\toprule`,
      cols.map((c) => tx(c.label)).join(" & ") + " \\\\", `\\midrule`,
      ...t.rows.map((r) => cols.map((c) => tx(cell(r, c))).join(" & ") + " \\\\"), `\\bottomrule`, `\\end{tabular}`,
      ...(t.note ? [`\\par\\smallskip\\footnotesize ${tx(t.note)}`] : []), `\\end{table}`].join("\n");
  }
  return "";
}

/* ═════════════ 색 — OKLab 보간(발산색) */
const hex2rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const gam = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
function toLab(h) {
  const [r, g, b] = hex2rgb(h).map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b), m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b), s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromLab([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3, m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3, s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map((c) => Math.round(Math.max(0, Math.min(1, gam(c))) * 255).toString(16).padStart(2, "0")).join("");
}
const NEG = toLab("#e34948"), MID = toLab("#f0efec"), POS = toLab("#2a78d6");
function diverging(v) {   // −1 ~ 1
  if (!fin(v)) return "#ffffff";
  const t = Math.max(-1, Math.min(1, v)), [a, b] = t < 0 ? [MID, NEG] : [MID, POS], k = Math.abs(t);
  return fromLab(a.map((x, i) => x + (b[i] - x) * k));
}
const inkOn = (hex) => (toLab(hex)[0] > 0.68 ? "#1B1F23" : "#ffffff");

const API = { fin, clean, describe, quantileSorted, wilson, ranks, spearman, pearson, corrMatrix, kruskal, anova, chi2Indep, holm,
  tCDF, tInv, chi2SF, fSF, normSF2, ibeta, gammaP, gammaQ, bins, niceStep, ecdfPoints, fmtP, exportTable, diverging, inkOn };
if (typeof module !== "undefined" && module.exports) module.exports = API; else root.AIStats = API;
})(typeof globalThis !== "undefined" ? globalThis : this);
