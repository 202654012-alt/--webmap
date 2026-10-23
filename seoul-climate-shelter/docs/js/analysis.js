/* 분석 로직 (화면/지도와 무관한 순수 계산). 브라우저에서는 window.SCSAnalysis, Node.js에서는 require() 로 사용한다.
 *  - 데이터 디코딩 (정수 mm 델타 인코딩 -> 미터 Float64Array)
 *  - 분석 1: 구별 쉼터 개수, 자연 구간(Jenks)/분위수/등간격 분류, 색상 램프
 *  - 분석 2: 도로 -> 가장 가까운 쉼터 K곳(브랜드 조건), 클릭 지점 -> 가장 가까운 도로 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./geo.js'));
  else root.SCSAnalysis = factory(root.SCSGeo);
}(typeof self !== 'undefined' ? self : this, function (Geo) {
  'use strict';

  // ------------------------------------------------------------------
  // 데이터 디코딩
  // ------------------------------------------------------------------
  /** [x0, y0, dx1, dy1, ...] (정수, 단위 unit 분의 1 m) -> 절대 좌표 Float64Array (m) */
  function decodeFlat(flat, unitsPerMeter) {
    var n = flat.length / 2;
    var out = new Float64Array(flat.length);
    var x = flat[0], y = flat[1];
    out[0] = x / unitsPerMeter; out[1] = y / unitsPerMeter;
    for (var i = 1; i < n; i++) {
      x += flat[2 * i]; y += flat[2 * i + 1];
      out[2 * i] = x / unitsPerMeter; out[2 * i + 1] = y / unitsPerMeter;
    }
    return out;
  }

  function bboxOf(flatList) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (var k = 0; k < flatList.length; k++) {
      var f = flatList[k];
      for (var i = 0; i < f.length; i += 2) {
        if (f[i] < x0) x0 = f[i];
        if (f[i] > x1) x1 = f[i];
        if (f[i + 1] < y0) y0 = f[i + 1];
        if (f[i + 1] > y1) y1 = f[i + 1];
      }
    }
    return [x0, y0, x1, y1];
  }

  function loadDistricts(json) {
    var upm = json.unit === 'mm' ? 1000 : 1;
    return json.districts.map(function (d) {
      var rings = d.rings.map(function (r) { return decodeFlat(r, upm); });
      return { name: d.name, code: d.code, rings: rings, bbox: bboxOf(rings) };
    });
  }

  function loadShelters(json) {
    var f = json.fields;
    var ix = {};
    f.forEach(function (name, i) { ix[name] = i; });
    return json.rows.map(function (r) {
      return {
        id: r[ix.id], brand: r[ix.brand], name: r[ix.name], gu: r[ix.gu],
        addr: r[ix.addr], hours: r[ix.hours], x: r[ix.x], y: r[ix.y]
      };
    });
  }

  function loadRoads(json) {
    var upm = json.unit === 'mm' ? 1000 : 1;
    var sigName = json.sigs.map(function (s) { return s[1]; });
    return json.roads.map(function (r, id) {
      var parts = r[4].map(function (p) { return decodeFlat(p, upm); });
      return {
        id: id, name: json.names[r[0]], gu: sigName[r[1]],
        length: r[2], width: r[3], parts: parts, bbox: bboxOf(parts)
      };
    });
  }

  // ------------------------------------------------------------------
  // 분석 1 : 구별 개수 + 분류
  // ------------------------------------------------------------------
  /** even-odd 규칙. rings 는 Float64Array(flat) 배열 */
  function pointInRings(x, y, rings) {
    var inside = false;
    for (var k = 0; k < rings.length; k++) {
      var r = rings[k], n = r.length / 2;
      for (var i = 0; i < n; i++) {
        var j = (i + 1) % n;
        var x1 = r[2 * i], y1 = r[2 * i + 1], x2 = r[2 * j], y2 = r[2 * j + 1];
        if ((y1 > y) !== (y2 > y) && x < (x2 - x1) * (y - y1) / (y2 - y1) + x1) inside = !inside;
      }
    }
    return inside;
  }

  /** 구 이름 -> 쉼터 개수. 어느 구에도 속하지 않은 쉼터는 outside 로 센다. */
  function countByDistrict(districts, shelters) {
    var counts = {};
    districts.forEach(function (d) { counts[d.name] = 0; });
    var outside = 0;
    shelters.forEach(function (s) {
      var hit = null;
      for (var i = 0; i < districts.length; i++) {
        var d = districts[i], b = d.bbox;
        if (s.x < b[0] || s.x > b[2] || s.y < b[1] || s.y > b[3]) continue;
        if (pointInRings(s.x, s.y, d.rings)) { hit = d.name; break; }
      }
      if (hit === null) outside++; else counts[hit]++;
    });
    return { counts: counts, outside: outside };
  }

  /** 자연 구간(Jenks, Fisher 최적 분할). 고유값 단위로 분할하므로 같은 값이 서로 다른 클래스로 갈라지지 않는다.
   *  반환: 각 클래스의 상한 값 배열 (마지막 = 최댓값) */
  function jenksBreaks(values, k) {
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    var uniq = [], w = [];
    sorted.forEach(function (v) {
      if (uniq.length && uniq[uniq.length - 1] === v) w[w.length - 1]++;
      else { uniq.push(v); w.push(1); }
    });
    var m = uniq.length;
    k = Math.min(k, m);
    if (k <= 1) return [uniq[m - 1]];

    var W = [0], S = [0], S2 = [0];
    for (var i = 0; i < m; i++) {
      W.push(W[i] + w[i]);
      S.push(S[i] + w[i] * uniq[i]);
      S2.push(S2[i] + w[i] * uniq[i] * uniq[i]);
    }
    function cost(a, b) { // uniq[a..b] 한 클래스의 제곱합 편차
      var ww = W[b + 1] - W[a], s = S[b + 1] - S[a], s2 = S2[b + 1] - S2[a];
      return s2 - s * s / ww;
    }
    var dp = [], from = [];
    for (var c = 0; c < k; c++) { dp.push(new Array(m).fill(Infinity)); from.push(new Array(m).fill(0)); }
    for (var j = 0; j < m; j++) dp[0][j] = cost(0, j);
    for (c = 1; c < k; c++) {
      for (j = c; j < m; j++) {
        for (var a = c; a <= j; a++) {
          var v = dp[c - 1][a - 1] + cost(a, j);
          if (v < dp[c][j]) { dp[c][j] = v; from[c][j] = a; }
        }
      }
    }
    var breaks = [];
    j = m - 1;
    for (c = k - 1; c >= 0; c--) {
      breaks.push(uniq[j]);
      j = c > 0 ? from[c][j] - 1 : -1;
    }
    return breaks.reverse();
  }

  /** 분위수(선형 보간). 마지막 경계 = 최댓값 */
  function quantileBreaks(values, k) {
    var v = values.slice().sort(function (a, b) { return a - b; });
    var n = v.length, out = [];
    for (var i = 1; i < k; i++) {
      var h = (n - 1) * i / k, lo = Math.floor(h);
      out.push(v[lo] + (h - lo) * (v[Math.min(lo + 1, n - 1)] - v[lo]));
    }
    out.push(v[n - 1]);
    return out;
  }

  /** 등간격 */
  function equalBreaks(values, k) {
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values), out = [];
    for (var i = 1; i < k; i++) out.push(lo + (hi - lo) * i / k);
    out.push(hi);
    return out;
  }

  function computeBreaks(method, values, k) {
    if (method === 'quantile') return quantileBreaks(values, k);
    if (method === 'equal') return equalBreaks(values, k);
    return jenksBreaks(values, k);
  }

  /** 값이 속한 클래스 번호 (0부터). 경계값은 아래 클래스에 포함 */
  function classIndex(value, breaks) {
    for (var i = 0; i < breaks.length; i++) if (value <= breaks[i] + 1e-9) return i;
    return breaks.length - 1;
  }

  /** 정수(개수) 값을 위한 범례 라벨: 클래스 i 에 들어오는 정수 범위 */
  function integerRangeLabel(i, breaks, minValue) {
    var lo = i === 0 ? minValue : Math.floor(breaks[i - 1] + 1e-9) + 1;
    var hi = Math.floor(breaks[i] + 1e-9);
    if (lo > hi) return null;
    return lo === hi ? String(lo) : lo + '–' + hi;
  }

  /** 단일 색상 계열 (연함 -> 중간 -> 진함). QGIS 스크립트/플러그인과 같은 색을 쓴다 */
  var COLOR_SCHEMES = {
    blue:   { label: '파랑', stops: ['#deebf7', '#6baed6', '#08306b'] },
    green:  { label: '초록', stops: ['#e5f5e0', '#74c476', '#00441b'] },
    orange: { label: '주황', stops: ['#fee6ce', '#fd8d3c', '#7f2704'] },
    red:    { label: '빨강', stops: ['#fee0d2', '#fb6a4a', '#67000d'] },
    purple: { label: '보라', stops: ['#efedf5', '#9e9ac8', '#3f007d'] }
  };

  function hexToRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }

  /** t(0~1) 위치의 색 (3개 정지점 사이 선형 보간) */
  function rampColor(scheme, t) {
    var st = COLOR_SCHEMES[scheme].stops.map(hexToRgb);
    t = Math.max(0, Math.min(1, t));
    var seg = t < 0.5 ? 0 : 1;
    var u = (t - seg * 0.5) / 0.5;
    var a = st[seg], b = st[seg + 1];
    var rgb = [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * u); });
    return '#' + rgb.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('');
  }

  /** 클래스 i / n 번째 색 (가장 낮은 클래스 = 가장 연한 색) */
  function classColor(scheme, i, n) {
    return rampColor(scheme, n <= 1 ? 0 : i / (n - 1));
  }

  // ------------------------------------------------------------------
  // 분석 2 : 도로 -> 가까운 쉼터 / 클릭 -> 가까운 도로
  // ------------------------------------------------------------------
  /** 도로 하나에서 가장 가까운 쉼터 k곳. brandSet 이 null 이면 전체 브랜드. 거리 단위 m(EPSG:5186 평면거리) */
  function nearestShelters(road, shelters, k, brandSet) {
    var list = [];
    for (var i = 0; i < shelters.length; i++) {
      var s = shelters[i];
      if (brandSet && !brandSet.has(s.brand)) continue;
      var r = Geo.closestOnParts(s.x, s.y, road.parts);
      list.push({ shelter: s, dist: r.dist, cx: r.x, cy: r.y });
    }
    list.sort(function (a, b) { return a.dist - b.dist || a.shelter.id - b.shelter.id; });
    return list.slice(0, k);
  }

  /** 도로 bbox 를 격자 셀에 담아 두고 영역/최근접 질의를 빠르게 처리 */
  function RoadIndex(roads, cell) {
    this.roads = roads;
    this.cell = cell || 500;
    this.grid = new Map();
    var c = this.cell;
    for (var i = 0; i < roads.length; i++) {
      var b = roads[i].bbox;
      var cx0 = Math.floor(b[0] / c), cx1 = Math.floor(b[2] / c);
      var cy0 = Math.floor(b[1] / c), cy1 = Math.floor(b[3] / c);
      for (var cx = cx0; cx <= cx1; cx++) {
        for (var cy = cy0; cy <= cy1; cy++) {
          var key = cx * 4096 + cy;
          var arr = this.grid.get(key);
          if (!arr) { arr = []; this.grid.set(key, arr); }
          arr.push(i);
        }
      }
    }
  }

  /** 영역(x0,y0,x1,y1)과 bbox 가 겹치는 도로 id 목록 */
  RoadIndex.prototype.query = function (x0, y0, x1, y1) {
    var c = this.cell, seen = new Set(), out = [];
    var cx0 = Math.floor(x0 / c), cx1 = Math.floor(x1 / c), cy0 = Math.floor(y0 / c), cy1 = Math.floor(y1 / c);
    for (var cx = cx0; cx <= cx1; cx++) {
      for (var cy = cy0; cy <= cy1; cy++) {
        var arr = this.grid.get(cx * 4096 + cy);
        if (!arr) continue;
        for (var i = 0; i < arr.length; i++) {
          var id = arr[i];
          if (seen.has(id)) continue;
          seen.add(id);
          var b = this.roads[id].bbox;
          if (b[2] < x0 || b[0] > x1 || b[3] < y0 || b[1] > y1) continue;
          out.push(id);
        }
      }
    }
    return out;
  };

  /** (x, y) 에서 maxDist 안에 있는 가장 가까운 도로. 없으면 null */
  RoadIndex.prototype.nearest = function (x, y, maxDist) {
    var ids = this.query(x - maxDist, y - maxDist, x + maxDist, y + maxDist);
    var best = null;
    for (var i = 0; i < ids.length; i++) {
      var road = this.roads[ids[i]];
      var r = Geo.closestOnParts(x, y, road.parts);
      if (r.dist > maxDist) continue;
      if (best === null || r.dist < best.dist || (r.dist === best.dist && road.id < best.road.id)) {
        best = { road: road, dist: r.dist, x: r.x, y: r.y };
      }
    }
    return best;
  };

  return {
    decodeFlat: decodeFlat,
    loadDistricts: loadDistricts,
    loadShelters: loadShelters,
    loadRoads: loadRoads,
    pointInRings: pointInRings,
    countByDistrict: countByDistrict,
    jenksBreaks: jenksBreaks,
    quantileBreaks: quantileBreaks,
    equalBreaks: equalBreaks,
    computeBreaks: computeBreaks,
    classIndex: classIndex,
    integerRangeLabel: integerRangeLabel,
    COLOR_SCHEMES: COLOR_SCHEMES,
    rampColor: rampColor,
    classColor: classColor,
    nearestShelters: nearestShelters,
    RoadIndex: RoadIndex
  };
}));
