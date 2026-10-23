# -*- coding: utf-8 -*-
"""
외부 라이브러리(GDAL, pyshp, shapely) 없이 shp/dbf를 읽는 최소 리더와 기하 함수.
- build_data.py : 웹 앱용 데이터(JSON) 생성
- make_expected.py : QGIS/웹 결과와 비교할 기대값 생성
"""
import math
import struct


def read_dbf(path, encoding='utf-8'):
    """dbf를 읽어 [ {필드명: 문자열} ] 리스트로 반환한다."""
    with open(path, 'rb') as f:
        head = f.read(32)
        n_rec = struct.unpack('<I', head[4:8])[0]
        header_len, rec_len = struct.unpack('<HH', head[8:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            name = d[:11].split(b'\x00')[0].decode(encoding, 'replace')
            fields.append((name, d[16]))
        f.seek(header_len)
        rows = []
        for _ in range(n_rec):
            rec = f.read(rec_len)
            pos, row = 1, {}
            for name, length in fields:
                row[name] = rec[pos:pos + length].decode(encoding, 'replace').strip()
                pos += length
            rows.append(row)
    return rows


def read_shp(path):
    """shp를 읽는다. 포인트는 (x, y), 선/면은 [[(x, y), ...], ...] (파트 리스트), 빈 도형은 None."""
    with open(path, 'rb') as f:
        data = f.read()
    pos, out = 100, []
    while pos < len(data):
        _, content_len = struct.unpack('>2i', data[pos:pos + 8])
        pos += 8
        c = data[pos:pos + content_len * 2]
        pos += content_len * 2
        shape_type = struct.unpack('<i', c[:4])[0]
        if shape_type == 0:
            out.append(None)
        elif shape_type == 1:
            out.append(struct.unpack('<2d', c[4:20]))
        elif shape_type in (3, 5):
            n_parts, n_pts = struct.unpack('<2i', c[36:44])
            parts = struct.unpack('<%di' % n_parts, c[44:44 + 4 * n_parts])
            off = 44 + 4 * n_parts
            v = struct.unpack('<%dd' % (2 * n_pts), c[off:off + 16 * n_pts])
            pts = list(zip(v[0::2], v[1::2]))
            out.append([pts[parts[i]:(parts[i + 1] if i + 1 < n_parts else n_pts)] for i in range(n_parts)])
        else:
            raise ValueError('지원하지 않는 도형 유형: %d' % shape_type)
    return out


def point_in_rings(pt, rings):
    """even-odd 규칙으로 점이 (구멍 포함) 폴리곤 안에 있는지 판정."""
    x, y = pt
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def _seg_closest(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return ax + t * dx, ay + t * dy


def point_to_polyline(p, parts):
    """점 -> 폴리라인(여러 파트) 최단거리(m)."""
    best = float('inf')
    for part in parts:
        for i in range(len(part) - 1):
            cx, cy = _seg_closest(p, part[i], part[i + 1])
            best = min(best, math.hypot(p[0] - cx, p[1] - cy))
    return best


# ----------------------------------------------------------------------
# 좌표 변환: Transverse Mercator (GRS80)  <->  WGS84 경위도
#   EPSG:5186 (Korea 2000 / Central Belt 2010) 파라미터는 서울_*.prj 에서 가져옴:
#   중앙자오선 127.0, 원점위도 38.0, 축척 1.0, 가산 동쪽 200000, 가산 북쪽 600000
# ----------------------------------------------------------------------
class TransverseMercator:
    A = 6378137.0
    F = 1 / 298.257222101

    def __init__(self, lon0, lat0, k0, false_easting, false_northing):
        self.e2 = self.F * (2 - self.F)
        self.lon0 = math.radians(lon0)
        self.lat0 = math.radians(lat0)
        self.k0 = k0
        self.fe = false_easting
        self.fn = false_northing

    def _arc(self, phi):
        e2 = self.e2
        return self.A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
                         - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
                         + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
                         - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))

    def to_lonlat(self, x, y):
        e2, a = self.e2, self.A
        m = self._arc(self.lat0) + (y - self.fn) / self.k0
        e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
        mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
        phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
                + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
                + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
                + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
        ep2 = e2 / (1 - e2)
        c1 = ep2 * math.cos(phi1) ** 2
        t1 = math.tan(phi1) ** 2
        n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
        r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
        d = (x - self.fe) / (n1 * self.k0)
        lat = phi1 - (n1 * math.tan(phi1) / r1) * (
            d ** 2 / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
        lon = self.lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
        return math.degrees(lon), math.degrees(lat)

    def from_lonlat(self, lon, lat):
        e2, a = self.e2, self.A
        phi, lam = math.radians(lat), math.radians(lon)
        ep2 = e2 / (1 - e2)
        n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
        t = math.tan(phi) ** 2
        c = ep2 * math.cos(phi) ** 2
        aa = (lam - self.lon0) * math.cos(phi)
        m = self._arc(phi)
        x = self.fe + self.k0 * n * (aa + (1 - t + c) * aa ** 3 / 6
                                     + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * aa ** 5 / 120)
        y = self.fn + self.k0 * (m - self._arc(self.lat0) + n * math.tan(phi) * (
            aa ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * aa ** 4 / 24
            + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * aa ** 6 / 720))
        return x, y


EPSG_5186 = TransverseMercator(127.0, 38.0, 1.0, 200000.0, 600000.0)
EPSG_5179 = TransverseMercator(127.5, 38.0, 0.9996, 1000000.0, 2000000.0)


def to_lonlat(x, y):
    """EPSG:5186 (x, y) -> (경도, 위도)."""
    return EPSG_5186.to_lonlat(x, y)


def from_lonlat(lon, lat):
    """(경도, 위도) -> EPSG:5186 (x, y)."""
    return EPSG_5186.from_lonlat(lon, lat)
