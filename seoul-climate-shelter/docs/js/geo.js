/* 좌표 변환(EPSG:5186 <-> WGS84)과 기하 함수.
 * 브라우저에서는 window.SCSGeo, Node.js(테스트)에서는 require() 로 사용한다.
 * 파라미터는 서울_*.prj 의 값: GRS80, 중앙자오선 127.0, 원점위도 38.0, 축척 1.0, 가산 동쪽 200000 / 북쪽 600000 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SCSGeo = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var A = 6378137.0;
  var F = 1 / 298.257222101;
  var E2 = F * (2 - F);
  var EP2 = E2 / (1 - E2);
  var LON0 = 127.0 * Math.PI / 180;
  var LAT0 = 38.0 * Math.PI / 180;
  var K0 = 1.0, FE = 200000.0, FN = 600000.0;
  var D2R = Math.PI / 180, R2D = 180 / Math.PI;

  function arc(phi) {
    var e4 = E2 * E2, e6 = e4 * E2;
    return A * ((1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
      - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
      + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
      - (35 * e6 / 3072) * Math.sin(6 * phi));
  }
  var M0 = arc(LAT0);

  /** EPSG:5186 (x, y)[m] -> [경도, 위도] */
  function toLonLat(x, y) {
    var e4 = E2 * E2, e6 = e4 * E2;
    var m = M0 + (y - FN) / K0;
    var e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
    var mu = m / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
    var phi1 = mu + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu)
      + (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu)
      + (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu)
      + (1097 * Math.pow(e1, 4) / 512) * Math.sin(8 * mu);
    var s = Math.sin(phi1), c = Math.cos(phi1), tn = Math.tan(phi1);
    var c1 = EP2 * c * c;
    var t1 = tn * tn;
    var n1 = A / Math.sqrt(1 - E2 * s * s);
    var r1 = A * (1 - E2) / Math.pow(1 - E2 * s * s, 1.5);
    var d = (x - FE) / (n1 * K0);
    var lat = phi1 - (n1 * tn / r1) * (
      d * d / 2
      - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * Math.pow(d, 4) / 24
      + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * Math.pow(d, 6) / 720);
    var lon = LON0 + (d - (1 + 2 * t1 + c1) * Math.pow(d, 3) / 6
      + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * Math.pow(d, 5) / 120) / c;
    return [lon * R2D, lat * R2D];
  }

  /** [경도, 위도] -> EPSG:5186 [x, y][m] */
  function fromLonLat(lon, lat) {
    var phi = lat * D2R, lam = lon * D2R;
    var s = Math.sin(phi), c = Math.cos(phi), tn = Math.tan(phi);
    var n = A / Math.sqrt(1 - E2 * s * s);
    var t = tn * tn;
    var cc = EP2 * c * c;
    var aa = (lam - LON0) * c;
    var m = arc(phi);
    var x = FE + K0 * n * (aa + (1 - t + cc) * Math.pow(aa, 3) / 6
      + (5 - 18 * t + t * t + 72 * cc - 58 * EP2) * Math.pow(aa, 5) / 120);
    var y = FN + K0 * (m - M0 + n * tn * (
      aa * aa / 2 + (5 - t + 9 * cc + 4 * cc * cc) * Math.pow(aa, 4) / 24
      + (61 - 58 * t + t * t + 600 * cc - 330 * EP2) * Math.pow(aa, 6) / 720));
    return [x, y];
  }

  /** 점(px, py)에서 폴리라인(flat=[x0,y0,x1,y1,...])까지의 최단거리와 가장 가까운 점 */
  function closestOnPolyline(px, py, flat) {
    var n = flat.length / 2;
    var bestD2 = Infinity, bx = flat[0], by = flat[1];
    if (n === 1) {
      return { dist: Math.hypot(px - bx, py - by), x: bx, y: by };
    }
    for (var i = 0; i < n - 1; i++) {
      var ax = flat[2 * i], ay = flat[2 * i + 1];
      var dx = flat[2 * i + 2] - ax, dy = flat[2 * i + 3] - ay;
      var l2 = dx * dx + dy * dy;
      var t = l2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / l2;
      t = t < 0 ? 0 : (t > 1 ? 1 : t);
      var cx = ax + t * dx, cy = ay + t * dy;
      var ex = px - cx, ey = py - cy;
      var d2 = ex * ex + ey * ey;
      if (d2 < bestD2) { bestD2 = d2; bx = cx; by = cy; }
    }
    return { dist: Math.sqrt(bestD2), x: bx, y: by };
  }

  /** 파트가 여러 개인 도로에서 최단거리 */
  function closestOnParts(px, py, parts) {
    var best = null;
    for (var i = 0; i < parts.length; i++) {
      var r = closestOnPolyline(px, py, parts[i]);
      if (best === null || r.dist < best.dist) best = r;
    }
    return best;
  }

  return {
    toLonLat: toLonLat,
    fromLonLat: fromLonLat,
    closestOnPolyline: closestOnPolyline,
    closestOnParts: closestOnParts
  };
}));
