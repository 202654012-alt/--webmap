# -*- coding: utf-8 -*-
"""
콘솔용 PyQGIS 스크립트(pyqgis/analysis2_nearest5_shelters.py) 로직 검증:  python tests/pyqgis_console_test.py

QGIS 없이도 돌도록 qgis 모듈을 최소한의 가짜(fake)로 대체해 스크립트를 처음부터 끝까지 실행한다.
  - 도로 선택 -> 가까운 쉼터 5곳, 브랜드 조건(BRANDS / set_brands), 연결선, 자동 갱신 연결/해제
  - 데이터는 docs/data/*.json (웹 앱과 같은 데이터), 기대값은 tests/expected.json (shp 원본으로 따로 계산)
주의: QGIS API 자체의 동작(예: QgsGeometry.distance)은 검증하지 않는다. 그 부분은 QGIS 에서 직접 실행해 확인해야 한다.
"""
import contextlib
import io
import json
import math
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from shp_reader import _seg_closest, point_to_polyline  # noqa: E402

EXPECTED = json.load(open(os.path.join(ROOT, 'tests', 'expected.json'), encoding='utf-8'))
passed, failed = 0, []


def check(cond, msg):
    global passed
    if cond:
        passed += 1
    else:
        failed.append(msg)
        print('  ✗', msg)


# ----------------------------------------------------------------------
# 가짜 QGIS
# ----------------------------------------------------------------------
class Dummy:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Dummy()

    def __call__(self, *a, **k):
        return Dummy()

    @classmethod
    def createSimple(cls, *a, **k):
        return cls()


class Rect:
    def __init__(self, box=None):
        self.box = box

    def setMinimal(self):
        self.box = None

    def isNull(self):
        return self.box is None

    def combineExtentWith(self, other):
        if other.box is None:
            return
        if self.box is None:
            self.box = tuple(other.box)
        else:
            a, b = self.box, other.box
            self.box = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    def scale(self, f):
        pass


class Geom:
    """parts(선) 또는 pt(점)를 가진 최소 지오메트리"""

    def __init__(self, other=None, parts=None, pt=None):
        if isinstance(other, Geom):
            parts, pt = other.parts, other.pt
        self.parts, self.pt = parts, pt

    def isNull(self):
        return self.parts is None and self.pt is None

    def isEmpty(self):
        return False

    def transform(self, _):
        pass

    def boundingBox(self):
        pts = [p for part in self.parts for p in part] if self.parts else [self.pt]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return Rect((min(xs), min(ys), max(xs), max(ys)))

    def distance(self, other):
        line, pt = (self, other.pt) if self.parts else (other, self.pt)
        return point_to_polyline(pt, line.parts)

    def shortestLine(self, other):
        best = (float('inf'), None)
        for part in self.parts:
            for a, b in zip(part, part[1:]):
                c = _seg_closest(other.pt, a, b)
                d = math.hypot(other.pt[0] - c[0], other.pt[1] - c[1])
                if d < best[0]:
                    best = (d, c)
        return Geom(parts=[[best[1], other.pt]])


class Field:
    def __init__(self, name, *a, **k):
        self._name = name

    def name(self):
        return self._name


class Fields:
    def __init__(self, items=None):
        self.items = list(items or [])

    def lookupField(self, name):
        for i, f in enumerate(self.items):
            if f.name() == name:
                return i
        return -1

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


class Feature:
    def __init__(self, fields=None, fid=-1):
        self._fields, self._attrs, self._geom, self._id = fields, [], None, fid

    def fields(self):
        return self._fields

    def id(self):
        return self._id

    def attributes(self):
        return list(self._attrs)

    def setAttributes(self, a):
        assert len(a) == len(self._fields), '속성 개수(%d)와 필드 개수(%d)가 다름' % (len(a), len(self._fields))
        self._attrs = list(a)

    def setGeometry(self, g):
        self._geom = g

    def geometry(self):
        return self._geom

    def hasGeometry(self):
        return self._geom is not None

    def __getitem__(self, key):
        return self._attrs[self._fields.lookupField(key) if isinstance(key, str) else key]


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, f):
        self.slots.append(f)

    def disconnect(self, f):
        self.slots.remove(f)

    def emit(self, *a):
        for f in list(self.slots):
            f(*a)


class Crs:
    def isGeographic(self):
        return False

    def authid(self):
        return 'EPSG:5186'

    def __eq__(self, other):
        return isinstance(other, Crs)

    def __ne__(self, other):
        return not self == other


CRS = Crs()


class Provider:
    def __init__(self, layer):
        self.layer = layer

    def addAttributes(self, fields):
        self.layer._fields.items.extend(fields)
        return True

    def deleteFeatures(self, ids):
        self.layer._feats = [f for f in self.layer._feats if f.id() not in set(ids)]
        return True

    def addFeatures(self, feats):
        for f in feats:
            f._id = self.layer._next_id
            self.layer._next_id += 1
            self.layer._feats.append(f)
        return True, feats


class Layer:
    def __init__(self, geometry='Point', name='', provider='memory'):
        self._name, self._fields, self._feats, self._next_id = name, Fields(), [], 0
        self._selected, self.selectionChanged = [], Signal()
        self.removed = False

    def name(self):
        return self._name

    def id(self):
        return 'layer-' + self._name

    def setCrs(self, c):
        pass

    def crs(self):
        return CRS

    def dataProvider(self):
        return Provider(self)

    def updateFields(self):
        pass

    def fields(self):
        return self._fields

    def getFeatures(self):
        return iter(list(self._feats))

    def featureCount(self):
        return len(self._feats)

    def updateExtents(self):
        pass

    def extent(self):
        return Rect(None)

    def triggerRepaint(self):
        pass

    def setRenderer(self, r):
        pass

    def setLabeling(self, x):
        pass

    def setLabelsEnabled(self, x):
        pass

    def selectedFeatures(self):
        return [f for f in self._feats if f.id() in self._selected]

    def selectedFeatureCount(self):
        return len(self._selected)

    def select(self, ids):
        self._selected = list(ids)
        self.selectionChanged.emit(list(ids), [], True)


class Project:
    _inst = None

    def __init__(self):
        self.layers = []

    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def mapLayersByName(self, name):
        return [l for l in self.layers if l.name() == name]

    def addMapLayer(self, layer):
        self.layers.append(layer)

    def removeMapLayer(self, layer_id):
        self.layers = [l for l in self.layers if l.id() != layer_id]


def install_fake_qgis():
    core = types.ModuleType('qgis.core')
    for name in ['QgsCoordinateTransform', 'QgsLineSymbol', 'QgsMarkerSymbol', 'QgsPalLayerSettings',
                 'QgsSingleSymbolRenderer', 'QgsTextBufferSettings', 'QgsTextFormat', 'QgsVectorLayerSimpleLabeling']:
        setattr(core, name, Dummy)
    core.QgsFeature, core.QgsGeometry, core.QgsRectangle = Feature, Geom, Rect
    core.QgsField, core.QgsProject, core.QgsVectorLayer = Field, Project, Layer
    gui = types.ModuleType('qgis.PyQt.QtGui')
    gui.QColor = Dummy
    qtcore = types.ModuleType('qgis.PyQt.QtCore')
    qtcore.QMetaType = types.SimpleNamespace(Type=types.SimpleNamespace(Int=1, Double=2, QString=3))
    pyqt = types.ModuleType('qgis.PyQt')
    top = types.ModuleType('qgis')
    for mod in (top, core, pyqt, gui, qtcore):
        sys.modules[mod.__name__] = mod
    return top


# ----------------------------------------------------------------------
# 데이터 (docs/data/*.json 을 파이썬으로 복원)
# ----------------------------------------------------------------------
def decode(flat):
    pts, x, y = [], 0, 0
    for i in range(0, len(flat), 2):
        x, y = (flat[i], flat[i + 1]) if i == 0 else (x + flat[i], y + flat[i + 1])
        pts.append((x / 1000.0, y / 1000.0))
    return pts


def build_layers(road_ids):
    sj = json.load(open(os.path.join(ROOT, 'docs', 'data', 'shelters.json'), encoding='utf-8'))
    rj = json.load(open(os.path.join(ROOT, 'docs', 'data', 'roads.json'), encoding='utf-8'))
    shelter = Layer('Point', '서울시_기후동행쉼터')
    shelter._fields = Fields([Field(n) for n in ['순번', '쉼터_구', '쉼터명', '구이름', '도로명주소', 'X', 'Y', '운영시간']])
    for r in sj['rows']:
        f = Feature(shelter._fields, r[0])
        f.setAttributes([r[0], r[1], r[2], r[3], r[4], r[6], r[7], r[5]])
        f.setGeometry(Geom(pt=(r[6], r[7])))
        shelter._feats.append(f)
    road = Layer('LineString', '서울_도로')
    road._fields = Fields([Field(n) for n in ['RN', 'SIG_CD', 'ROAD_LT']])
    for rid in road_ids:
        rd = rj['roads'][rid]
        f = Feature(road._fields, rid)
        f.setAttributes([rj['names'][rd[0]], '11110', rd[2]])
        f.setGeometry(Geom(parts=[decode(p) for p in rd[4]]))
        road._feats.append(f)
    return shelter, road


def run_script(road_ids, brands_setting=None):
    top = install_fake_qgis()
    Project._inst = None
    shelter, road = build_layers(road_ids)
    proj = Project.instance()
    proj.layers = [road, shelter]
    path = os.path.join(ROOT, 'pyqgis', 'analysis2_nearest5_shelters.py')
    src = open(path, encoding='utf-8').read()
    if brands_setting is not None:
        assert 'BRANDS = []' in src
        src = src.replace('BRANDS = []', 'BRANDS = %r' % (brands_setting,))
    ns = {'__name__': '__main__'}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(src, path, 'exec'), ns)
    return ns, proj, road, out.getvalue()


def case(road_id, brands):
    return next(c for c in EXPECTED['nearest'] if c['roadId'] == road_id and c['brands'] == brands)


def result_rows(proj, name='가까운_기후동행쉼터'):
    layer = proj.mapLayersByName(name)[0]
    rows = []
    for f in layer.getFeatures():
        rows.append((f['rank'], f['쉼터명'], f['쉼터_구'], f['dist_m']))
    return sorted(rows)


def verify(proj, road_id, brands, label):
    exp = case(road_id, brands)
    rows = result_rows(proj)
    check([r[1] for r in rows] == [x['name'] for x in exp['results']], '%s: 쉼터 이름/순서 %s' % (label, [r[1] for r in rows]))
    check(all(abs(r[3] - x['dist']) <= 0.002 for r, x in zip(rows, exp['results'])), '%s: 거리 오차 <= 2mm' % label)
    check([r[2] for r in rows] == [x['brand'] for x in exp['results']], '%s: 브랜드' % label)


def main():
    road_ids = [0, 60974]
    print('[콘솔-1] 스크립트 실행 / 도로 선택 / 브랜드 조건')
    ns, proj, road, out = run_script(road_ids)
    check(ns['brand_counts'] == EXPECTED['brandTotals'], '브랜드 현황 %s' % ns['brand_counts'])
    check('[브랜드 현황]' in out and '자동 갱신 ON' in out, '시작 메시지 출력')
    check(len(proj.mapLayersByName('가까운_기후동행쉼터')) == 1 and len(proj.mapLayersByName('도로-쉼터_연결선')) == 1, '결과 레이어 2개 생성')
    check(len(road.selectionChanged.slots) == 1, '도로 선택 신호에 자동 갱신 연결')

    road.select([0])
    verify(proj, 0, None, '도로 0 / 전체')
    lines = list(proj.mapLayersByName('도로-쉼터_연결선')[0].getFeatures())
    check(len(lines) == 5, '연결선 5개')
    first = sorted(lines, key=lambda f: f['rank'])[0]
    seg = first.geometry().parts[0]
    check(abs(math.hypot(seg[0][0] - seg[1][0], seg[0][1] - seg[1][1]) - first['dist_m']) <= 0.002, '연결선 길이 = 거리')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns['set_brands']('CU')
    verify(proj, 0, ['CU'], '도로 0 / set_brands(CU)')
    check('대상: CU' in buf.getvalue(), '출력에 대상 브랜드 표시')
    with contextlib.redirect_stdout(io.StringIO()):
        ns['set_brands']('cu', 'kt')
    verify(proj, 0, ['CU', 'KT'], '도로 0 / set_brands(cu, kt) 대소문자 무시')
    with contextlib.redirect_stdout(io.StringIO()):
        ns['set_brands'](['신한은행'])
    verify(proj, 0, ['신한은행'], '도로 0 / 리스트로 전달')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns['set_brands']('LG')
    check('찾을 수 없습니다' in buf.getvalue() and ns['ACTIVE_BRANDS'] == {'신한은행'.casefold()}, '없는 브랜드는 안내하고 기존 조건 유지')
    verify(proj, 0, ['신한은행'], '없는 브랜드 입력 후에도 결과 유지')

    with contextlib.redirect_stdout(io.StringIO()):
        ns['set_brands']()
    verify(proj, 0, None, '도로 0 / set_brands() 전체 복원')

    ns['K'] = 3
    with contextlib.redirect_stdout(io.StringIO()):
        ns['set_brands']('CU')
    check(len(result_rows(proj)) == 3, 'K=3 -> 3곳')
    ns['K'] = 5

    with contextlib.redirect_stdout(io.StringIO()):
        ns['set_brands']('KT')
        road.select([60974])
    verify(proj, 60974, ['KT'], '도로 60974 / KT')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns['set_brands']()
        road.select([0, 60974])
    check(len(result_rows(proj)) == 10, '도로 2개 선택 -> 10행')

    ns['stop_auto_update']()
    check(len(road.selectionChanged.slots) == 0, 'stop_auto_update() 로 연결 해제')
    before = result_rows(proj)
    with contextlib.redirect_stdout(io.StringIO()):
        road.select([0])
    check(result_rows(proj) == before, '해제 후에는 선택해도 갱신되지 않음')

    print('[콘솔-2] 시작 설정 BRANDS')
    ns, proj, road, out = run_script(road_ids, brands_setting=['CU'])
    check(ns['ACTIVE_BRANDS'] == {'cu'} and '현재 조건: CU' in out, "BRANDS=['CU'] 로 시작")
    with contextlib.redirect_stdout(io.StringIO()):
        road.select([0])
    verify(proj, 0, ['CU'], '시작부터 CU만')
    try:
        run_script(road_ids, brands_setting=['LG'])
        check(False, '없는 브랜드 설정은 오류여야 함')
    except Exception as exc:
        check('사용 가능한 값' in str(exc), '없는 브랜드 설정은 사용 가능한 값을 안내: %s' % exc)

    print('\n결과: 통과 %d / 실패 %d' % (passed, len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
