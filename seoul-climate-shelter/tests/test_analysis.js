/* JS 분석 모듈 검증:  node tests/test_analysis.js
 * 파이썬이 shp 원본으로 따로 계산한 기대값(tests/expected.json)과, 웹에 올라가는 JSON 데이터로 계산한 JS 결과를 비교한다. */
'use strict';
const fs = require('fs');
const path = require('path');
const Geo = require('../docs/js/geo.js');
const An = require('../docs/js/analysis.js');

const read = (p) => JSON.parse(fs.readFileSync(path.join(__dirname, p), 'utf8'));
const exp = read('expected.json');
let failed = 0, passed = 0;
function check(cond, msg) {
  if (cond) { passed++; } else { failed++; console.log('  ✗ ' + msg); }
}
const near = (a, b, tol) => Math.abs(a - b) <= tol;

let t0 = Date.now();
const districts = An.loadDistricts(read('../docs/data/districts.json'));
const shelters = An.loadShelters(read('../docs/data/shelters.json'));
const roads = An.loadRoads(read('../docs/data/roads.json'));
console.log(`데이터 로드/디코딩: ${Date.now() - t0} ms  (구 ${districts.length}, 쉼터 ${shelters.length}, 도로 ${roads.length})`);
t0 = Date.now();
const index = new An.RoadIndex(roads, 500);
console.log(`도로 격자 인덱스 생성: ${Date.now() - t0} ms  (셀 ${index.grid.size}개)`);

// 1) 구별 개수 ---------------------------------------------------------
console.log('\n[1] 구별 쉼터 개수');
const res = An.countByDistrict(districts, shelters);
check(res.outside === 0, `구 경계 밖 쉼터 0 (실제 ${res.outside})`);
for (const [name, cnt] of Object.entries(exp.districtCounts)) {
  check(res.counts[name] === cnt, `${name}: JS ${res.counts[name]} / 기대 ${cnt}`);
}
const total = Object.values(res.counts).reduce((a, b) => a + b, 0);
check(total === exp.totalShelters, `합계 ${total} / ${exp.totalShelters}`);
const brandTotals = {};
shelters.forEach((s) => { brandTotals[s.brand] = (brandTotals[s.brand] || 0) + 1; });
check(JSON.stringify(brandTotals) === JSON.stringify(exp.brandTotals) ||
  Object.keys(exp.brandTotals).every((b) => brandTotals[b] === exp.brandTotals[b]), '브랜드별 합계 일치');

// 2) 분류 경계 ---------------------------------------------------------
console.log('[2] 분류 경계 (Jenks / 분위수 / 등간격)');
const values = Object.values(res.counts);
for (const k of [3, 4, 5, 6, 7]) {
  const jb = An.jenksBreaks(values, k);
  const okJ = exp.classification.jenks[String(k)].optimalBreaks.some((o) => JSON.stringify(o) === JSON.stringify(jb));
  check(okJ, `Jenks k=${k}: JS ${JSON.stringify(jb)} / 최적해 ${JSON.stringify(exp.classification.jenks[String(k)].optimalBreaks)}`);
  const qb = An.quantileBreaks(values, k), eb = An.equalBreaks(values, k);
  check(qb.every((v, i) => near(v, exp.classification.quantile[String(k)][i], 1e-9)), `분위수 k=${k}`);
  check(eb.every((v, i) => near(v, exp.classification.equal[String(k)][i], 1e-9)), `등간격 k=${k}`);
}
const j5 = An.jenksBreaks(values, 5);
console.log('    Jenks 5단계 경계:', j5, '| 범례:', j5.map((_, i) => An.integerRangeLabel(i, j5, Math.min(...values))).join(', '));
check(An.rampColor('blue', 0) === '#deebf7' && An.rampColor('blue', 1) === '#08306b' && An.rampColor('blue', 0.5) === '#6baed6', '색상 램프 양끝/중간 색');

// 3) 도로 -> 가까운 쉼터 ------------------------------------------------
console.log('[3] 도로 -> 가까운 쉼터 K곳 (브랜드 조건 포함)');
for (const c of exp.nearest) {
  const set = c.brands ? new Set(c.brands) : null;
  const got = An.nearestShelters(roads[c.roadId], shelters, c.k, set);
  const label = `도로 ${c.roadId}(${c.roadName}) 브랜드=${c.brands ? c.brands.join('+') : '전체'}`;
  check(got.length === c.results.length, `${label}: 개수`);
  const ids = got.map((g) => g.shelter.id).join(','), eids = c.results.map((r) => r.id).join(',');
  check(ids === eids, `${label}: 순위 JS [${ids}] / 기대 [${eids}]`);
  check(got.every((g, i) => c.results[i] && near(g.dist, c.results[i].dist, 0.002)),
    `${label}: 거리 오차 <= 2mm`);
  check(got.every((g) => !set || set.has(g.shelter.brand)), `${label}: 브랜드 필터`);
}

// 4) 클릭 지점 -> 가장 가까운 도로 -----------------------------------------
console.log('[4] 클릭 지점 -> 가장 가까운 도로');
for (const c of exp.nearestRoad) {
  const got = index.nearest(c.x, c.y, 100);
  check(got && got.road.id === c.roadId && near(got.dist, c.dist, 0.002),
    `클릭(${c.x.toFixed(1)}, ${c.y.toFixed(1)}): JS ${got && got.road.id} (${got && got.dist.toFixed(3)} m) / 기대 ${c.roadId} (${c.dist.toFixed(3)} m)`);
}
check(index.nearest(0, 0, 50) === null, '서울 밖 지점은 null');

// 5) 좌표 변환 -----------------------------------------------------------
console.log('[5] 좌표 변환');
let worst = 0;
for (let i = 0; i < 2000; i++) {
  const x = 185000 + Math.random() * 30000, y = 535000 + Math.random() * 30000;
  const ll = Geo.toLonLat(x, y), back = Geo.fromLonLat(ll[0], ll[1]);
  worst = Math.max(worst, Math.hypot(x - back[0], y - back[1]));
}
check(worst < 1e-3, `왕복 오차 ${worst.toExponential(2)} m`);
const ll0 = Geo.toLonLat(198000, 551000);
check(ll0[0] > 126.9 && ll0[0] < 127.1 && ll0[1] > 37.5 && ll0[1] < 37.6, `서울 중심부 좌표 범위 (${ll0[0].toFixed(5)}, ${ll0[1].toFixed(5)})`);

console.log(`\n결과: 통과 ${passed} / 실패 ${failed}`);
process.exit(failed ? 1 : 0);
