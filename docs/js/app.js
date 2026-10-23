/* 서울 기후동행쉼터 공간분석 - 화면/지도 코드 (계산은 analysis.js, 좌표는 geo.js) */
(function () {
  'use strict';

  const Geo = window.SCSGeo;
  const An = window.SCSAnalysis;

  const ROAD_MIN_ZOOM = 14;      // 이 줌 이상에서만 도로를 그린다
  const ROAD_MAX_DRAW = 6000;    // 한 화면에 그릴 최대 도로 수
  const CLICK_PX = 14;           // 도로 클릭 허용 반경(픽셀)
  const BRAND_COLORS = { 'KT': '#d9480f', 'CU': '#7c3aed', '신한은행': '#0b7285' };
  const brandColor = (b) => BRAND_COLORS[b] || '#6b7280';

  const $ = (sel) => document.querySelector(sel);
  const nf0 = new Intl.NumberFormat('ko-KR');
  const nf1 = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const state = {
    tab: 'count',
    districts: [], shelters: [], roads: [], index: null,
    counts: null, outside: 0, breaks: null, classOf: {},
    road: null, allBrands: [], brands: new Set(), k: 5, results: [], markers: []
  };
  const polys = [];          // { d, poly }
  const layers = {};

  // ------------------------------------------------------------------
  // 지도 기본 설정
  // ------------------------------------------------------------------
  const map = L.map('map', { preferCanvas: true, minZoom: 9, maxZoom: 19 }).setView([37.5665, 126.978], 11);
  const carto = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    subdomains: 'abcd', maxZoom: 20,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
  }).addTo(map);
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  });
  layers.districts = L.featureGroup().addTo(map);
  layers.roads = L.layerGroup();
  layers.shelters = L.featureGroup();
  layers.result = L.featureGroup();

  const toLatLng = (x, y) => { const p = Geo.toLonLat(x, y); return [p[1], p[0]]; };
  function flatToLatLngs(flat) {
    const out = [];
    for (let i = 0; i < flat.length; i += 2) out.push(toLatLng(flat[i], flat[i + 1]));
    return out;
  }

  function setLayer(layer, on) {
    if (on && !map.hasLayer(layer)) map.addLayer(layer);
    if (!on && map.hasLayer(layer)) map.removeLayer(layer);
  }

  function setStatus(text, kind) {
    const box = $('#status');
    box.textContent = text || '';
    box.className = 'status' + (kind ? ' ' + kind : '');
  }

  // ------------------------------------------------------------------
  // URL 해시 (결과 공유/재현용)  예) #tab=nearest&road=60974&brands=CU
  // ------------------------------------------------------------------
  function selectedBrandSet() {
    return state.brands.size === state.allBrands.length ? null : new Set(state.brands);
  }

  function updateHash() {
    try {
      const p = new URLSearchParams();
      p.set('tab', state.tab);
      if (state.tab === 'nearest') {
        if (state.road) p.set('road', state.road.id);
        const set = selectedBrandSet();
        if (set) p.set('brands', Array.from(set).join(','));
        if (state.k !== 5) p.set('k', state.k);
      } else {
        const m = $('#class-method').value, c = $('#class-count').value, col = $('#class-color').value;
        if (m !== 'jenks') p.set('method', m);
        if (c !== '5') p.set('classes', c);
        if (col !== 'blue') p.set('color', col);
      }
      history.replaceState(null, '', '#' + p.toString());
    } catch (e) { /* file:// 등에서는 무시 */ }
  }

  // ------------------------------------------------------------------
  // 분석 1 : 구별 쉼터 개수 단계구분도
  // ------------------------------------------------------------------
  function buildDistrictLayers() {
    state.districts.forEach((d) => {
      const poly = L.polygon(d.rings.map(flatToLatLngs), { color: '#4b5563', weight: 1, fillColor: '#dddddd', fillOpacity: 0.85 });
      poly.on('click', (ev) => { if (state.tab === 'count') showDistrictPopup(d, ev.latlng); });
      layers.districts.addLayer(poly);
      polys.push({ d, poly });
    });
  }

  function showDistrictPopup(d, latlng) {
    const cnt = state.counts[d.name];
    const rank = Object.keys(state.counts).filter((n) => state.counts[n] > cnt).length + 1;
    L.popup().setLatLng(latlng)
      .setContent('<b>' + esc(d.name) + '</b><br>기후동행쉼터 ' + cnt + '곳<br>25개 구 중 ' + rank + '위')
      .openOn(map);
  }

  function renderLabels() {
    const on = state.tab === 'count' && $('#show-labels').checked;
    polys.forEach(({ d, poly }) => {
      poly.unbindTooltip();
      if (on) {
        poly.bindTooltip(esc(d.name) + '<br>' + state.counts[d.name], { permanent: true, direction: 'center', className: 'gu-label' });
      }
    });
  }

  function renderCount() {
    const method = $('#class-method').value;
    const k = parseInt($('#class-count').value, 10);
    const scheme = $('#class-color').value;
    const names = state.districts.map((d) => d.name);
    const vals = names.map((n) => state.counts[n]);
    const breaks = An.computeBreaks(method, vals, k);
    const n = breaks.length;
    const minV = Math.min.apply(null, vals), maxV = Math.max.apply(null, vals);
    state.breaks = breaks;

    const perClass = new Array(n).fill(0);
    polys.forEach(({ d, poly }) => {
      const ci = An.classIndex(state.counts[d.name], breaks);
      state.classOf[d.name] = ci;
      perClass[ci]++;
      poly.setStyle({ fillColor: An.classColor(scheme, ci, n), fillOpacity: 0.85, color: '#4b5563', weight: 1 });
    });

    // 요약 카드
    const top = names.reduce((a, b) => (state.counts[b] > state.counts[a] ? b : a));
    const low = names.reduce((a, b) => (state.counts[b] < state.counts[a] ? b : a));
    $('#summary').innerHTML =
      '<div><b>' + nf0.format(vals.reduce((a, b) => a + b, 0)) + '곳</b><span>전체 쉼터' + (state.outside ? ' (경계 밖 ' + state.outside + ')' : '') + '</span></div>' +
      '<div><b>' + maxV + '곳</b><span>최다 ' + esc(top) + '</span></div>' +
      '<div><b>' + minV + '곳</b><span>최소 ' + esc(low) + '</span></div>';

    // 범례
    const legend = [];
    for (let i = 0; i < n; i++) {
      const label = An.integerRangeLabel(i, breaks, minV);
      if (label === null) continue;
      legend.push('<li><span class="swatch" style="background:' + An.classColor(scheme, i, n) + '"></span>' +
        label + '곳<span class="cnt">' + perClass[i] + '개 구</span></li>');
    }
    $('#legend').innerHTML = legend.join('');

    // 구별 순위
    const sorted = names.slice().sort((a, b) => state.counts[b] - state.counts[a] || a.localeCompare(b, 'ko'));
    $('#rank-list').innerHTML = sorted.map((name) =>
      '<li data-name="' + esc(name) + '"><span>' + esc(name) + '</span>' +
      '<span class="bar" style="width:' + Math.max(4, state.counts[name] / maxV * 100) + '%;background:' +
      An.classColor(scheme, state.classOf[name], n) + '"></span>' +
      '<span class="n">' + state.counts[name] + '</span></li>').join('');

    renderLabels();
    updateHash();
  }

  function styleOutline() {
    polys.forEach(({ poly }) => poly.setStyle({ fillOpacity: 0, color: '#64748b', weight: 1.2 }));
  }

  // ------------------------------------------------------------------
  // 분석 2 : 도로 선택 -> 가까운 쉼터 K곳 (브랜드 조건)
  // ------------------------------------------------------------------
  function shelterPopup(s, rank, dist) {
    return '<b>' + (rank ? rank + '. ' : '') + esc(s.name) + '</b><br>' + esc(s.brand) + ' · ' + esc(s.gu) +
      '<br>' + esc(s.addr) + '<br>운영시간 ' + esc(s.hours) +
      (dist != null ? '<br>도로까지 ' + nf1.format(dist) + ' m' : '');
  }

  function buildShelterLayer() {
    state.shelters.forEach((s) => {
      const m = L.circleMarker(toLatLng(s.x, s.y), { radius: 5, color: '#ffffff', weight: 1, fillColor: brandColor(s.brand), fillOpacity: 0.95 });
      m.bindPopup(shelterPopup(s));
      m._scs = s;
      layers.shelters.addLayer(m);
    });
  }

  function refreshShelterStyle() {
    const filtering = state.tab === 'nearest';
    layers.shelters.eachLayer((m) => {
      const on = !filtering || state.brands.has(m._scs.brand);
      m.setStyle({ fillOpacity: on ? 0.95 : 0.12, opacity: on ? 1 : 0.2 });
    });
  }

  function buildBrandUI() {
    const counts = {};
    state.shelters.forEach((s) => { counts[s.brand] = (counts[s.brand] || 0) + 1; });
    state.allBrands = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    state.brands = new Set(state.allBrands);
    const box = $('#brand-list');
    box.innerHTML = state.allBrands.map((b) =>
      '<label class="brand"><input type="checkbox" value="' + esc(b) + '" checked />' +
      '<span class="dot" style="background:' + brandColor(b) + '"></span><span>' + esc(b) + '</span>' +
      '<em>' + counts[b] + '곳</em><button type="button" class="only" data-brand="' + esc(b) + '">만</button></label>').join('');
    box.addEventListener('change', (e) => {
      if (!e.target.matches('input[type=checkbox]')) return;
      state.brands = new Set(Array.from(box.querySelectorAll('input:checked')).map((i) => i.value));
      refreshShelterStyle();
      recompute();
    });
    box.addEventListener('click', (e) => {
      const btn = e.target.closest('.only');
      if (!btn) return;
      e.preventDefault();
      setBrands([btn.dataset.brand]);
      recompute();
    });
  }

  function setBrands(list) {
    state.brands = new Set(list);
    document.querySelectorAll('#brand-list input').forEach((i) => { i.checked = state.brands.has(i.value); });
    refreshShelterStyle();
  }

  function recompute() {
    layers.result.clearLayers();
    state.results = [];
    state.markers = [];
    const tbl = $('#result-table'), info = $('#road-info');
    const road = state.road;
    if (!road) {
      tbl.hidden = true; info.hidden = true;
      $('#csv-nearest').hidden = true; $('#clear-road').hidden = true;
      setStatus('');
      updateHash();
      return;
    }

    const roadLine = L.polyline(road.parts.map(flatToLatLngs), { color: '#f59e0b', weight: 6, opacity: 0.95 });
    layers.result.addLayer(roadLine);
    info.hidden = false;
    info.innerHTML = '<b>' + esc(road.name) + '</b><span>' + esc(road.gu) + ' · 길이 ' + nf0.format(road.length) +
      'm · 폭 ' + road.width + 'm · QGIS $id = ' + road.id + '</span>';
    $('#clear-road').hidden = false;

    const set = selectedBrandSet();
    if (state.brands.size === 0) {
      tbl.hidden = true; $('#csv-nearest').hidden = true;
      setStatus('브랜드를 하나 이상 선택하세요.', 'warn');
      updateHash();
      return;
    }

    const list = An.nearestShelters(road, state.shelters, state.k, set);
    state.results = list;
    const bounds = roadLine.getBounds();

    list.forEach((r, i) => {
      const p = toLatLng(r.shelter.x, r.shelter.y), c = toLatLng(r.cx, r.cy);
      layers.result.addLayer(L.polyline([c, p], { color: '#64748b', weight: 2, dashArray: '5 5', interactive: false }));
      const marker = L.marker(p, {
        icon: L.divIcon({ className: 'rank-icon', html: '<span>' + (i + 1) + '</span>', iconSize: [26, 26], iconAnchor: [13, 13] }),
        zIndexOffset: 1000
      });
      marker.bindPopup(shelterPopup(r.shelter, i + 1, r.dist));
      layers.result.addLayer(marker);
      state.markers.push(marker);
      bounds.extend(p);
    });

    tbl.hidden = false;
    $('#csv-nearest').hidden = false;
    tbl.querySelector('tbody').innerHTML = list.map((r, i) =>
      '<tr data-i="' + i + '"><td><span class="rank-badge">' + (i + 1) + '</span></td>' +
      '<td>' + esc(r.shelter.name) + '<small>' + esc(r.shelter.gu) + '</small></td>' +
      '<td><span class="chip" style="background:' + brandColor(r.shelter.brand) + '">' + esc(r.shelter.brand) + '</span></td>' +
      '<td class="num">' + nf1.format(r.dist) + '</td></tr>').join('');

    const target = set ? Array.from(set).join('+') : '전체 브랜드';
    const pool = state.shelters.filter((s) => !set || set.has(s.brand)).length;
    if (list.length < state.k) {
      setStatus('대상 ' + target + ' 쉼터가 ' + pool + '곳뿐이라 ' + list.length + '곳만 표시합니다.', 'warn');
    } else if (list.length) {
      const far = list[list.length - 1].dist;
      setStatus('대상: ' + target + ' (' + pool + '곳) · ' + list.length + '번째 쉼터까지 ' + nf1.format(far) + ' m' +
        (far > 3000 ? ' — 멀리 떨어져 있어요' : ''), far > 3000 ? 'warn' : '');
    }

    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 17 });
    updateHash();
  }

  function selectRoad(road) {
    state.road = road;
    recompute();
  }

  function selectRoadAt(latlng) {
    if (!state.index) return false;
    if (map.getZoom() < ROAD_MIN_ZOOM) {
      setStatus('도로를 선택하려면 지도를 ' + ROAD_MIN_ZOOM + '단계 이상으로 확대하세요. (현재 ' + map.getZoom() + '단계)', 'warn');
      return false;
    }
    const xy = Geo.fromLonLat(latlng.lng, latlng.lat);
    const metersPerPixel = 156543.03392 * Math.cos(latlng.lat * Math.PI / 180) / Math.pow(2, map.getZoom());
    const tolerance = Math.max(8, CLICK_PX * metersPerPixel);
    const hit = state.index.nearest(xy[0], xy[1], tolerance);
    if (!hit) {
      setStatus('클릭한 곳 근처에 도로가 없습니다. 도로 위(회색 선)를 클릭하세요.', 'warn');
      return false;
    }
    selectRoad(hit.road);
    return true;
  }

  // ---- 도로 그리기(현재 화면에 보이는 도로만) ----
  const roadCache = new Map();
  let roadTimer = null;

  function roadLatLngs(road) {
    let v = roadCache.get(road.id);
    if (!v) { v = road.parts.map(flatToLatLngs); roadCache.set(road.id, v); }
    return v;
  }

  function refreshRoads() {
    layers.roads.clearLayers();
    const hint = $('#zoom-hint');
    if (state.tab !== 'nearest' || !state.index) { hint.hidden = true; return; }
    if (!map.hasLayer(layers.roads)) { hint.hidden = true; return; }
    const z = map.getZoom();
    if (z < ROAD_MIN_ZOOM) {
      hint.hidden = false;
      hint.textContent = '도로는 지도를 ' + ROAD_MIN_ZOOM + '단계 이상 확대하면 표시됩니다. (현재 ' + z + '단계)';
      return;
    }
    const b = map.getBounds();
    const corners = [[b.getWest(), b.getSouth()], [b.getEast(), b.getSouth()], [b.getWest(), b.getNorth()], [b.getEast(), b.getNorth()]]
      .map((c) => Geo.fromLonLat(c[0], c[1]));
    const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]);
    const ids = state.index.query(Math.min.apply(null, xs), Math.min.apply(null, ys), Math.max.apply(null, xs), Math.max.apply(null, ys));
    if (ids.length > ROAD_MAX_DRAW) {
      hint.hidden = false;
      hint.textContent = '도로가 너무 많아 일부만 표시했습니다. 더 확대하면 모두 보입니다.';
      ids.length = ROAD_MAX_DRAW;
    } else {
      hint.hidden = true;
    }
    ids.forEach((id) => {
      layers.roads.addLayer(L.polyline(roadLatLngs(state.roads[id]), { color: '#94a3b8', weight: 2, opacity: 0.9, interactive: false }));
    });
  }

  function scheduleRoadRefresh() {
    clearTimeout(roadTimer);
    roadTimer = setTimeout(refreshRoads, 120);
  }

  // ------------------------------------------------------------------
  // 탭 전환
  // ------------------------------------------------------------------
  function setTab(name) {
    state.tab = name;
    document.querySelectorAll('.tab').forEach((btn) => {
      const on = btn.dataset.tab === name;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $('#tab-count').hidden = name !== 'count';
    $('#tab-nearest').hidden = name !== 'nearest';
    map.closePopup();
    if (name === 'count') {
      setLayer(layers.roads, false);
      setLayer(layers.shelters, false);
      setLayer(layers.result, false);
      $('#zoom-hint').hidden = true;
      renderCount();
    } else {
      styleOutline();
      setLayer(layers.roads, true);
      setLayer(layers.shelters, true);
      setLayer(layers.result, true);
      layers.shelters.bringToFront();
      layers.result.bringToFront();
      renderLabels();
      refreshRoads();
      recompute();
    }
    refreshShelterStyle();
    updateHash();
  }

  // ------------------------------------------------------------------
  // CSV 저장
  // ------------------------------------------------------------------
  function downloadCsv(filename, rows) {
    const cell = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const csv = '\ufeff' + rows.map((r) => r.map(cell).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function csvCount() {
    const rows = [['구', '기후동행쉼터 개수', '단계']];
    state.districts.forEach((d) => rows.push([d.name, state.counts[d.name], state.classOf[d.name] + 1]));
    downloadCsv('구별_기후동행쉼터_개수.csv', rows);
  }

  function csvNearest() {
    if (!state.road) return;
    const rows = [['순위', '쉼터명', '브랜드', '구', '주소', '운영시간', '거리(m)', '도로명', '도로 $id']];
    state.results.forEach((r, i) => rows.push([i + 1, r.shelter.name, r.shelter.brand, r.shelter.gu, r.shelter.addr,
      r.shelter.hours, r.dist.toFixed(3), state.road.name, state.road.id]));
    downloadCsv('가까운_기후동행쉼터_도로' + state.road.id + '.csv', rows);
  }

  // ------------------------------------------------------------------
  // 이벤트 연결 / 초기화
  // ------------------------------------------------------------------
  function bindUI() {
    document.querySelectorAll('.tab').forEach((btn) => btn.addEventListener('click', () => setTab(btn.dataset.tab)));
    ['#class-count', '#class-method', '#class-color'].forEach((s) => $(s).addEventListener('change', renderCount));
    $('#show-labels').addEventListener('change', renderLabels);
    $('#csv-count').addEventListener('click', csvCount);
    $('#csv-nearest').addEventListener('click', csvNearest);
    $('#clear-road').addEventListener('click', () => { state.road = null; recompute(); });
    $('#k-select').addEventListener('change', () => { state.k = parseInt($('#k-select').value, 10); recompute(); });

    $('#rank-list').addEventListener('click', (e) => {
      const li = e.target.closest('li');
      if (!li) return;
      const hit = polys.find((p) => p.d.name === li.dataset.name);
      if (!hit) return;
      map.fitBounds(hit.poly.getBounds(), { maxZoom: 13, padding: [20, 20] });
      showDistrictPopup(hit.d, hit.poly.getBounds().getCenter());
    });
    $('#result-table tbody').addEventListener('click', (e) => {
      const tr = e.target.closest('tr');
      if (!tr) return;
      const i = parseInt(tr.dataset.i, 10), r = state.results[i];
      if (!r) return;
      map.setView(toLatLng(r.shelter.x, r.shelter.y), Math.max(map.getZoom(), 16));
      state.markers[i].openPopup();
    });

    map.on('click', (e) => { if (state.tab === 'nearest') selectRoadAt(e.latlng); });
    map.on('moveend', scheduleRoadRefresh);
    map.on('overlayadd', (e) => { if (e.layer === layers.roads) refreshRoads(); });
  }

  function applyHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const method = p.get('method'), classes = p.get('classes'), color = p.get('color');
    if (method && $('#class-method').querySelector('option[value="' + method + '"]')) $('#class-method').value = method;
    if (classes && Array.from($('#class-count').options).some((o) => o.value === classes)) $('#class-count').value = classes;
    if (color && An.COLOR_SCHEMES[color]) $('#class-color').value = color;
    const k = parseInt(p.get('k'), 10);
    if (k >= 1 && k <= 10) { state.k = k; $('#k-select').value = String(k); }
    const brands = p.get('brands');
    if (brands) {
      const list = brands.split(',').filter((b) => state.allBrands.indexOf(b) >= 0);
      if (list.length) setBrands(list);
    }
    const roadId = parseInt(p.get('road'), 10);
    if (roadId >= 0 && state.roads[roadId]) state.road = state.roads[roadId];
    return p.get('tab') === 'nearest' ? 'nearest' : 'count';
  }

  function fatal(err) {
    const box = $('#loading');
    box.classList.add('error');
    const offline = location.protocol === 'file:';
    box.innerHTML = '<div><strong>데이터를 불러오지 못했습니다.</strong><span>' + esc(err && err.message ? err.message : err) +
      '</span><span>' + (offline
        ? '파일을 더블클릭(file://)으로 열면 데이터를 읽을 수 없습니다. GitHub Pages 주소로 열거나, 폴더에서 <code>python -m http.server</code> 실행 후 http://localhost:8000 으로 접속하세요.'
        : '네트워크 상태를 확인하고 새로고침해 주세요.') + '</span></div>';
  }

  async function boot() {
    const label = $('#loading-text');
    const getJson = async (name, text) => {
      const res = await fetch('data/' + name);
      if (!res.ok) throw new Error(name + ' (' + res.status + ')');
      label.textContent = text + ' 도착, 처리 중…';
      return res.json();
    };
    label.textContent = '구 경계 · 쉼터 · 도로 데이터를 내려받는 중… (도로 약 10MB)';
    const [dj, sj, rj] = await Promise.all([
      getJson('districts.json', '구 경계'), getJson('shelters.json', '쉼터'), getJson('roads.json', '도로')]);

    state.districts = An.loadDistricts(dj);
    state.shelters = An.loadShelters(sj);
    state.roads = An.loadRoads(rj);
    state.index = new An.RoadIndex(state.roads, 500);
    const res = An.countByDistrict(state.districts, state.shelters);
    state.counts = res.counts;
    state.outside = res.outside;

    // 선택 목록 채우기
    $('#class-color').innerHTML = Object.keys(An.COLOR_SCHEMES)
      .map((k) => '<option value="' + k + '">' + An.COLOR_SCHEMES[k].label + '</option>').join('');
    $('#k-select').innerHTML = Array.from({ length: 10 }, (_, i) => '<option value="' + (i + 1) + '"' + (i + 1 === 5 ? ' selected' : '') + '>' + (i + 1) + '곳</option>').join('');

    buildDistrictLayers();
    buildShelterLayer();
    buildBrandUI();
    bindUI();
    map.fitBounds(layers.districts.getBounds(), { padding: [20, 20] });
    L.control.layers({ 'CARTO 밝은 지도': carto, 'OpenStreetMap': osm },
      { '구 경계': layers.districts, '기후동행쉼터': layers.shelters, '도로 (확대 시)': layers.roads, '분석 결과': layers.result },
      { collapsed: true }).addTo(map);

    setTab(applyHash());   // 해시로 복원된 도로/브랜드는 setTab -> recompute() 에서 그려진다
    $('#loading').hidden = true;
  }

  window.SCSApp = {
    state, map, layers, polys,
    setTab, setBrands, recompute, selectRoad, selectRoadAt, renderCount, refreshRoads,
    ready: boot().catch((err) => { fatal(err); throw err; })
  };
  window.SCSApp.ready.catch(() => {});
}());
