// 연구용 통계(docs/aihub-stats.js)를 알려진 값과 대조한다 — node tests/test_stats.js
// 기준: t·χ²·F 분포표, R kruskal.test 도움말 예(Hollander & Wolfe), 2×2 χ²(보정 없음), Wilson 구간, 대칭 표본의 왜도·첨도.
const S = require("../docs/aihub-stats.js");
let fail = 0;
const near = (name, got, want, tol = 1e-3) => {
  const ok = Math.abs(got - want) <= tol;
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${got} (기대 ${want})`);
};
near("t(0.975, 9)", S.tInv(0.975, 9), 2.2622);
near("t(0.975, 1)", S.tInv(0.975, 1), 12.7062);
near("χ² SF(3.8415, 1)", S.chi2SF(3.841459, 1), 0.05, 1e-5);
near("χ² SF(11.0705, 5)", S.chi2SF(11.0705, 5), 0.05, 1e-5);
near("F SF(4.2565; 2, 9)", S.fSF(4.256495, 2, 9), 0.05, 1e-5);
near("정규 양측 p(1.96)", S.normSF2(1.959964), 0.05, 1e-5);
const x = [2.9, 3.0, 2.5, 2.6, 3.2], y = [3.8, 2.7, 4.0, 2.4], z = [2.8, 3.4, 3.7, 2.2, 2.0];
const kw = S.kruskal([x, y, z]);
near("Kruskal–Wallis H", kw.H, 0.7714);
near("Kruskal–Wallis p", kw.p, 0.68, 0.005);
const c = S.chi2Indep([[10, 20], [30, 40]]);
near("χ² 2×2", c.chi2, 0.7937);
near("χ² 2×2 p", c.p, 0.373);
const [lo, hi] = S.wilson(8, 10);
near("Wilson 하한", lo, 0.4902); near("Wilson 상한", hi, 0.9433);
const d = S.describe([1, 2, 3, 4, 5]);
near("왜도(대칭)", d.skew, 0); near("첨도(균등 5점)", d.kurt, -1.2);
near("평균 95% CI 하한", d.ciLo, 3 - 2.7764 * Math.sqrt(2.5 / 5));
near("Spearman ρ(동점)", S.spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]).rho, 0.8208);
near("Holm", S.holm([0.01, 0.04, 0.03])[1], 0.06, 1e-12);
// 상관 행렬 = 짝마다 직접 계산한 값
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const cols = Array.from({ length: 4 }, (_, v) => Array.from({ length: 500 }, (_, i) => (rnd() < 0.1 ? null : Math.round((rnd() + v * i / 500) * 10) / 10)));
const M = S.corrMatrix(cols);
near("상관 행렬 ↔ 직접", M[1][3].r, S.spearman(cols[1], cols[3]).rho, 1e-12);
if (fail) { console.error(`실패 ${fail}개`); process.exit(1); }
console.log("통계 검사 통과");
