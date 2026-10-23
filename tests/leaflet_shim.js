/* 테스트 전용 Leaflet 대역(shim).
 * 네트워크 없이 docs/js/app.js 의 화면 로직(패널, 이벤트, 계산 연결)을 실제 브라우저에서 검증하기 위해
 * app.js 가 사용하는 Leaflet API 범위만 흉내 낸다. 지도 렌더링 자체는 검증하지 않는다. */
(function () {
  'use strict';

  function Bounds(latlngs) {
    this.n = -Infinity; this.s = Infinity; this.e = -Infinity; this.w = Infinity;
    (latlngs || []).forEach(this.extend, this);
  }
  Bounds.prototype.extend = function (p) {
    if (p instanceof Bounds) { this.extend([p.s, p.w]); this.extend([p.n, p.e]); return this; }
    var lat = Array.isArray(p) ? p[0] : p.lat, lng = Array.isArray(p) ? p[1] : p.lng;
    this.n = Math.max(this.n, lat); this.s = Math.min(this.s, lat);
    this.e = Math.max(this.e, lng); this.w = Math.min(this.w, lng);
    return this;
  };
  Bounds.prototype.getWest = function () { return this.w; };
  Bounds.prototype.getEast = function () { return this.e; };
  Bounds.prototype.getNorth = function () { return this.n; };
  Bounds.prototype.getSouth = function () { return this.s; };
  Bounds.prototype.getCenter = function () { return { lat: (this.n + this.s) / 2, lng: (this.e + this.w) / 2 }; };

  function flatten(latlngs, out) {
    out = out || [];
    if (latlngs.length && typeof latlngs[0] === 'number') out.push(latlngs);
    else latlngs.forEach(function (x) { flatten(x, out); });
    return out;
  }

  function Layer() { this._h = {}; this.options = {}; }
  Layer.prototype.on = function (ev, cb) { (this._h[ev] = this._h[ev] || []).push(cb); return this; };
  Layer.prototype.fire = function (ev, e) { (this._h[ev] || []).forEach(function (cb) { cb(e); }); return this; };
  Layer.prototype.addTo = function (map) { map.addLayer(this); return this; };
  Layer.prototype.bindPopup = function (html) { this._popup = html; return this; };
  Layer.prototype.openPopup = function () { window.__shim.opened.push(this._popup); return this; };
  Layer.prototype.bindTooltip = function (html) { this._tooltip = html; return this; };
  Layer.prototype.unbindTooltip = function () { this._tooltip = null; return this; };
  Layer.prototype.setStyle = function (s) { this.options = Object.assign({}, this.options, s); return this; };

  function Group() { Layer.call(this); this.layers = []; }
  Group.prototype = Object.create(Layer.prototype);
  Group.prototype.addLayer = function (l) { this.layers.push(l); return this; };
  Group.prototype.clearLayers = function () { this.layers = []; return this; };
  Group.prototype.eachLayer = function (cb) { this.layers.forEach(cb); };
  Group.prototype.bringToFront = function () { return this; };
  Group.prototype.getBounds = function () {
    var b = new Bounds();
    this.layers.forEach(function (l) { if (l.getBounds) b.extend(l.getBounds()); });
    return b;
  };

  function Poly(latlngs, opts) {
    Layer.call(this);
    this.latlngs = latlngs; this.options = Object.assign({}, opts);
  }
  Poly.prototype = Object.create(Layer.prototype);
  Poly.prototype.getBounds = function () { return new Bounds(flatten(this.latlngs)); };

  function Marker(latlng, opts) { Layer.call(this); this.latlng = latlng; this.options = Object.assign({}, opts); }
  Marker.prototype = Object.create(Layer.prototype);
  Marker.prototype.getBounds = function () { return new Bounds([this.latlng]); };

  function MapShim() {
    Layer.call(this);
    this._zoom = 11; this._layers = new Set(); this._popup = null;
    this._bounds = new Bounds([[37.560, 126.970], [37.570, 126.990]]);   // refreshRoads() 가 쓰는 "현재 화면"
  }
  MapShim.prototype = Object.create(Layer.prototype);
  MapShim.prototype.setView = function (c, z) { if (z != null) this._zoom = z; return this; };
  MapShim.prototype.fitBounds = function (b, o) { this._zoom = (o && o.maxZoom) || 12; window.__shim.fits.push(b); return this; };
  MapShim.prototype.getZoom = function () { return this._zoom; };
  MapShim.prototype.getBounds = function () { return this._bounds; };
  MapShim.prototype.hasLayer = function (l) { return this._layers.has(l); };
  MapShim.prototype.addLayer = function (l) { this._layers.add(l); return this; };
  MapShim.prototype.removeLayer = function (l) { this._layers.delete(l); return this; };
  MapShim.prototype.closePopup = function () { this._popup = null; return this; };

  function Popup() { Layer.call(this); }
  Popup.prototype = Object.create(Layer.prototype);
  Popup.prototype.setLatLng = function (p) { this._ll = p; return this; };
  Popup.prototype.setContent = function (h) { this._html = h; return this; };
  Popup.prototype.openOn = function (map) { map._popup = this; window.__shim.opened.push(this._html); return this; };

  window.__shim = { opened: [], fits: [] };
  window.L = {
    map: function () { return new MapShim(); },
    tileLayer: function (url) { var l = new Layer(); l.url = url; return l; },
    featureGroup: function () { return new Group(); },
    layerGroup: function () { return new Group(); },
    polygon: function (l, o) { return new Poly(l, o); },
    polyline: function (l, o) { return new Poly(l, o); },
    circleMarker: function (ll, o) { return new Marker(ll, o); },
    marker: function (ll, o) { return new Marker(ll, o); },
    divIcon: function (o) { return o; },
    popup: function () { return new Popup(); },
    control: { layers: function (base, over) { var l = new Layer(); l.base = base; l.over = over; return l; } }
  };
}());
