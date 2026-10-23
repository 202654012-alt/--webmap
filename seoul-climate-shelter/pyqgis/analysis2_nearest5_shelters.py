# -*- coding: utf-8 -*-
"""
분석 2 : 도로 객체를 선택하면 가장 가까운 기후동행쉼터 5곳을 새 레이어로 표시

[실행 방법]
QGIS > 플러그인 > 파이썬 콘솔 > 스크립트 편집기 열기 > 이 파일 열기 > 실행(▶)

[사용 방법]
1) 이 스크립트를 한 번 실행한다.
2) 지도에서 '객체 선택' 도구로 "서울_도로"의 도로 하나를 클릭해서 선택한다.
3) AUTO_UPDATE = True 이면 선택할 때마다 결과가 자동 갱신된다.
   (False 이면 도로를 선택한 뒤 스크립트를 다시 실행한다.)
4) 자동 갱신을 끄려면 콘솔에서  stop_auto_update()  를 입력한다.

[브랜드 선택]  (쉼터 레이어의 '쉼터_구' 필드: KT / CU / 신한은행)
  - 아래 설정의 BRANDS = ['CU'] 처럼 적고 실행하면 CU 쉼터 안에서만 가까운 5곳을 찾는다. ([] = 전체)
  - 실행한 뒤에 바꾸려면 콘솔에서  set_brands('CU')  /  set_brands('CU', 'KT')  /  set_brands()  (전체)
  - 선택 창으로 고르려면 콘솔에서  choose_brand()

[결과 레이어]
  - "가까운_기후동행쉼터"  : 쉼터 포인트 (rank=거리순위, dist_m=도로까지 거리(m))
  - "도로-쉼터_연결선"     : 도로에서 각 쉼터까지의 최단 연결선 (DRAW_LINKS=True 일 때)

[주의]
  - 거리는 도로선 전체에서 쉼터까지의 '직선거리'입니다. 도로망 경로 거리가 아닙니다.
  - 두 레이어는 미터 단위 투영좌표계여야 합니다 (이 과제 데이터는 EPSG:5186).
"""
import os

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsField,
)
from qgis.PyQt.QtGui import QColor

# =====================================================================
# 설정 (필요하면 여기만 수정)
# =====================================================================
ROAD_LAYER_NAME = '서울_도로'
SHELTER_LAYER_NAME = '서울시_기후동행쉼터'
DATA_DIR = r''                         # 레이어가 프로젝트에 없을 때 shp를 읽어올 폴더 (있으면 비워둠)

K = 5                                  # 찾을 쉼터 개수
MAX_ROADS = 20                         # 한 번에 처리할 최대 도로 수
ROAD_NAME_FIELD = 'RN'                 # 도로명 필드
SHELTER_NAME_FIELD = '쉼터명'          # 쉼터 이름 필드
BRAND_FIELD = '쉼터_구'                # 쉼터 브랜드(구분) 필드: KT / CU / 신한은행
BRANDS = []                            # 예) ['CU']  /  ['CU', 'KT']  /  [] = 전체 브랜드

RESULT_POINTS_NAME = '가까운_기후동행쉼터'
RESULT_LINES_NAME = '도로-쉼터_연결선'
DRAW_LINKS = True                      # 도로 -> 쉼터 연결선도 그릴지
ZOOM_TO_RESULT = True                  # 결과가 나오면 화면을 결과 범위로 이동할지
AUTO_UPDATE = True                     # 도로를 선택할 때마다 자동 갱신할지


# =====================================================================
# 함수
# =====================================================================
def get_layer(name):
    project = QgsProject.instance()
    found = project.mapLayersByName(name)
    if found:
        return found[0]
    if DATA_DIR:
        path = os.path.join(DATA_DIR, name + '.shp')
        if os.path.exists(path):
            layer = QgsVectorLayer(path, name, 'ogr')
            if layer.isValid():
                project.addMapLayer(layer)
                return layer
    raise Exception("레이어를 찾을 수 없습니다: '{}' (프로젝트에 불러오거나 DATA_DIR를 설정하세요)".format(name))


def make_field(name, kind, length=0, precision=0):
    """QGIS 3.38+ 는 QMetaType, 이전 버전은 QVariant 사용."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        t = {'int': QMetaType.Type.Int, 'double': QMetaType.Type.Double,
             'string': QMetaType.Type.QString}[kind]
        return QgsField(name, t, '', length, precision)
    except (ImportError, AttributeError, TypeError):
        from qgis.PyQt.QtCore import QVariant
        t = {'int': QVariant.Int, 'double': QVariant.Double, 'string': QVariant.String}[kind]
        return QgsField(name, t, '', length, precision)


def make_memory_layer(geometry, name, crs, fields):
    layer = QgsVectorLayer(geometry, name, 'memory')
    layer.setCrs(crs)
    layer.dataProvider().addAttributes(fields)
    layer.updateFields()
    return layer


def style_labels(layer, expression, size=11):
    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = True
    text_format = QgsTextFormat()
    text_format.setSize(size)
    text_format.setColor(QColor('#7f1d1d'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor('#ffffff'))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def remove_layers_named(name):
    for old in QgsProject.instance().mapLayersByName(name):
        QgsProject.instance().removeMapLayer(old.id())


def replace_features(layer, features):
    provider = layer.dataProvider()
    provider.deleteFeatures([f.id() for f in layer.getFeatures()])
    if features:
        provider.addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()


# =====================================================================
# 준비: 레이어/결과 레이어 생성
# =====================================================================
road_layer = get_layer(ROAD_LAYER_NAME)
shelter_layer = get_layer(SHELTER_LAYER_NAME)
road_crs = road_layer.crs()

if road_crs.isGeographic():
    raise Exception('도로 레이어가 경위도(도 단위) 좌표계입니다. 미터 단위 투영좌표계 레이어를 사용하세요.')

# 쉼터를 도로 좌표계로 맞춰서 메모리에 보관 (412곳 정도라 매번 읽지 않고 한 번만 읽음)
_to_road_crs = None
if shelter_layer.crs() != road_crs:
    _to_road_crs = QgsCoordinateTransform(shelter_layer.crs(), road_crs, QgsProject.instance())

shelter_items = []   # (원본 쉼터 feature, 도로 좌표계로 변환한 geometry)
for f in shelter_layer.getFeatures():
    if not f.hasGeometry() or f.geometry().isEmpty():
        continue
    g = QgsGeometry(f.geometry())
    if _to_road_crs is not None:
        g.transform(_to_road_crs)
    shelter_items.append((f, g))
print('[준비] 도로 {}개 / 쉼터 {}곳 / CRS {}'.format(road_layer.featureCount(), len(shelter_items), road_crs.authid()))


# ---- 브랜드 조건 (쉼터_구 필드: KT / CU / 신한은행) ----
def _norm(value):
    return str(value).strip().casefold()


brand_counts = {}
if shelter_layer.fields().lookupField(BRAND_FIELD) >= 0:
    for _f, _g in shelter_items:
        _key = str(_f[BRAND_FIELD]).strip()
        brand_counts[_key] = brand_counts.get(_key, 0) + 1
    print('[브랜드 현황] ' + ', '.join('{} {}곳'.format(b, n) for b, n in sorted(brand_counts.items(), key=lambda kv: -kv[1])))
elif BRANDS:
    raise Exception("브랜드 필드 '{}'를 쉼터 레이어에서 찾을 수 없습니다.".format(BRAND_FIELD))


def _validate_brands(names):
    known = {_norm(b) for b in brand_counts}
    unknown = [n for n in names if _norm(n) not in known]
    if unknown:
        raise Exception("브랜드 '{}'를 찾을 수 없습니다. 사용 가능한 값: {}".format(', '.join(unknown), ', '.join(brand_counts)))


ACTIVE_BRANDS = set()          # 비어 있으면 전체 브랜드
_validate_brands(BRANDS)
ACTIVE_BRANDS = {_norm(b) for b in BRANDS}

extra_fields = [
    make_field('rank', 'int'),
    make_field('dist_m', 'double', 20, 3),
    make_field('road_fid', 'int'),
    make_field('road_name', 'string', 254),
]

remove_layers_named(RESULT_POINTS_NAME)
remove_layers_named(RESULT_LINES_NAME)

points_layer = make_memory_layer('Point', RESULT_POINTS_NAME, road_crs,
                                 list(shelter_layer.fields()) + extra_fields)
points_layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
    'name': 'circle', 'color': '#dc2626', 'size': '4',
    'outline_color': '#ffffff', 'outline_width': '0.6'})))
style_labels(points_layer, '"rank"')

lines_layer = None
if DRAW_LINKS:
    lines_layer = make_memory_layer('LineString', RESULT_LINES_NAME, road_crs, extra_fields)
    lines_layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        'color': '#6b7280', 'width': '0.5', 'line_style': 'dash'})))
    QgsProject.instance().addMapLayer(lines_layer)   # 선을 먼저 추가해 점이 위에 그려지게 함
QgsProject.instance().addMapLayer(points_layer)


# =====================================================================
# 핵심: 선택한 도로 -> 가장 가까운 쉼터 K곳
# =====================================================================
def zoom_to(rect):
    try:
        canvas = iface.mapCanvas()
    except NameError:
        return
    xform = QgsCoordinateTransform(road_crs, canvas.mapSettings().destinationCrs(), QgsProject.instance())
    rect = xform.transformBoundingBox(rect)
    rect.scale(1.3)
    canvas.setExtent(rect)
    canvas.refresh()


def update_result(*_args):
    """도로 레이어의 현재 선택 객체로 결과 레이어를 다시 만든다."""
    roads = road_layer.selectedFeatures()
    if not roads:
        return          # 선택을 해제했을 때는 마지막 결과를 그대로 둔다
    if len(roads) > MAX_ROADS:
        print('※ 선택된 도로가 {}개라 앞의 {}개만 처리합니다.'.format(len(roads), MAX_ROADS))
        roads = roads[:MAX_ROADS]

    candidates = [(f, g) for f, g in shelter_items
                  if not ACTIVE_BRANDS or _norm(f[BRAND_FIELD]) in ACTIVE_BRANDS]
    brand_label = ', '.join(sorted(b for b in brand_counts if _norm(b) in ACTIVE_BRANDS)) if ACTIVE_BRANDS else '전체 브랜드'
    if not candidates:
        print('※ 선택한 브랜드({})의 쉼터가 없습니다.'.format(brand_label))
        return
    if len(candidates) < K:
        print('※ {} 쉼터가 {}곳뿐이라 {}곳만 표시합니다.'.format(brand_label, len(candidates), len(candidates)))

    point_feats, line_feats = [], []
    bounds = QgsRectangle()
    bounds.setMinimal()

    for road in roads:
        road_geom = road.geometry()
        if road_geom.isNull() or road_geom.isEmpty():
            continue
        road_name = str(road[ROAD_NAME_FIELD]) if road.fields().lookupField(ROAD_NAME_FIELD) >= 0 else ''
        bounds.combineExtentWith(road_geom.boundingBox())

        scored = sorted(
            ((road_geom.distance(g), f.id(), f, g) for f, g in candidates),
            key=lambda t: (t[0], t[1]),
        )[:K]

        print('\n[도로 id={} {}] 가장 가까운 기후동행쉼터 {}곳 (대상: {})'.format(road.id(), road_name, len(scored), brand_label))
        for rank, (dist, _, shelter, geom) in enumerate(scored, start=1):
            attrs_extra = [rank, round(dist, 3), road.id(), road_name]

            pf = QgsFeature(points_layer.fields())
            pf.setGeometry(QgsGeometry(geom))
            pf.setAttributes(list(shelter.attributes()) + attrs_extra)
            point_feats.append(pf)

            if lines_layer is not None and hasattr(road_geom, 'shortestLine'):
                lf = QgsFeature(lines_layer.fields())
                lf.setGeometry(road_geom.shortestLine(geom))
                lf.setAttributes(attrs_extra)
                line_feats.append(lf)

            shelter_name = shelter[SHELTER_NAME_FIELD] if shelter.fields().lookupField(SHELTER_NAME_FIELD) >= 0 else shelter.id()
            print('  {}. {} - {:,.1f} m'.format(rank, shelter_name, dist))

    replace_features(points_layer, point_feats)
    if lines_layer is not None:
        replace_features(lines_layer, line_feats)

    if ZOOM_TO_RESULT and not bounds.isNull():
        bounds.combineExtentWith(points_layer.extent())
        zoom_to(bounds)


# =====================================================================
# 브랜드 조건 바꾸기 (콘솔에서 호출)
# =====================================================================
def set_brands(*names):
    """브랜드 조건을 바꾸고, 선택된 도로가 있으면 바로 다시 계산한다.
    set_brands('CU')  /  set_brands('CU', 'KT')  /  set_brands()  <- 전체 브랜드"""
    global ACTIVE_BRANDS
    if len(names) == 1 and isinstance(names[0], (list, tuple, set)):
        names = tuple(names[0])
    names = [n for n in names if str(n).strip()]
    try:
        _validate_brands(names)
    except Exception as exc:
        print('※ ' + str(exc))
        return
    ACTIVE_BRANDS = {_norm(n) for n in names}
    print('[브랜드 조건] ' + (', '.join(names) if names else '전체 브랜드'))
    if road_layer.selectedFeatureCount() == 0:
        print('  도로를 선택하면 이 조건으로 가까운 쉼터를 찾습니다.')
    update_result()


def choose_brand():
    """브랜드를 고르는 작은 선택 창을 띄운다."""
    from qgis.PyQt.QtWidgets import QInputDialog
    names = sorted(brand_counts, key=lambda b: -brand_counts[b])
    labels = ['전체 브랜드'] + ['{} ({}곳)'.format(b, brand_counts[b]) for b in names]
    text, ok = QInputDialog.getItem(iface.mainWindow(), '쉼터 브랜드 선택', '가까운 쉼터를 찾을 브랜드', labels, 0, False)
    if ok:
        index = labels.index(text)
        set_brands() if index == 0 else set_brands(names[index - 1])


# =====================================================================
# 자동 갱신 연결 (스크립트를 다시 실행해도 중복 연결되지 않게 처리)
# =====================================================================
def stop_auto_update():
    """도로 선택 시 자동 갱신을 끈다."""
    handler = globals().get('_nn_handler')
    layer = globals().get('_nn_handler_layer')
    if handler is not None and layer is not None:
        try:
            layer.selectionChanged.disconnect(handler)
        except (TypeError, RuntimeError):
            pass
    globals()['_nn_handler'] = None
    globals()['_nn_handler_layer'] = None


stop_auto_update()   # 이전 실행에서 연결된 것이 있으면 먼저 해제

if AUTO_UPDATE:
    road_layer.selectionChanged.connect(update_result)
    _nn_handler = update_result
    _nn_handler_layer = road_layer
    print('\n[자동 갱신 ON] 지도에서 "{}" 도로를 선택하면 가까운 쉼터 {}곳이 표시됩니다.'.format(ROAD_LAYER_NAME, K))
    print('               끄려면 콘솔에서  stop_auto_update()  를 실행하세요.')
print('[브랜드] 현재 조건: {}  (바꾸기: set_brands(\'CU\') / 전체: set_brands() / 선택창: choose_brand())'.format(
    ', '.join(sorted(b for b in brand_counts if _norm(b) in ACTIVE_BRANDS)) if ACTIVE_BRANDS else '전체 브랜드'))

# 이미 선택된 도로가 있으면 바로 한 번 실행
update_result()
