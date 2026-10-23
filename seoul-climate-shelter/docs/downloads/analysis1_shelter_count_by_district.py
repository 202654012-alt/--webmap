# -*- coding: utf-8 -*-
"""
분석 1 : 서울 구별 기후동행쉼터 개수 -> 단계구분도 (적으면 연하게, 많으면 진하게)

[실행 방법]
QGIS > 플러그인 > 파이썬 콘솔 > 스크립트 편집기 열기 > 이 파일 열기 > 실행(▶)

[사전 준비]
프로젝트에 아래 두 레이어가 불러와져 있어야 합니다.
  - "서울_구"            (폴리곤, 구 이름 필드: NAME)
  - "서울시_기후동행쉼터"  (포인트)
(프로젝트에 없으면 DATA_DIR에 shp가 있는 폴더를 적어두면 자동으로 불러옵니다.)

[결과]
  - "구별_기후동행쉼터_개수" 레이어 추가 (shelter_cnt 필드 = 구별 개수)
  - Jenks 5단계 단계구분도 + 구 이름/개수 라벨
  - 콘솔에 구별 개수 순위표 출력
"""
import os

from qgis import processing
from qgis.core import (
    QgsClassificationEqualInterval,
    QgsClassificationJenks,
    QgsClassificationQuantile,
    QgsExpression,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsGraduatedSymbolRenderer,
    QgsPalLayerSettings,
    QgsProject,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor

# =====================================================================
# 설정 (필요하면 여기만 수정)
# =====================================================================
DISTRICT_LAYER_NAME = '서울_구'
SHELTER_LAYER_NAME = '서울시_기후동행쉼터'
DATA_DIR = r''                    # 예) r'C:\Users\PC\Downloads\기말고사'  (레이어가 이미 프로젝트에 있으면 비워둠)

NAME_FIELD = 'NAME'               # 구 이름 필드
COUNT_FIELD = 'shelter_cnt'       # 개수를 저장할 필드 이름
RESULT_LAYER_NAME = '구별_기후동행쉼터_개수'

N_CLASSES = 5                     # 단계 수
METHOD = 'jenks'                  # 'jenks'(자연 구간) | 'quantile'(분위수) | 'equal'(등간격)
COLOR = 'blue'                    # 'blue' | 'green' | 'orange' | 'red' | 'purple'
SHOW_LABELS = True                # 구 이름 + 개수 라벨

# 연함(적음) -> 중간 -> 진함(많음)
COLOR_SCHEMES = {
    'blue':   ('#deebf7', '#6baed6', '#08306b'),
    'green':  ('#e5f5e0', '#74c476', '#00441b'),
    'orange': ('#fee6ce', '#fd8d3c', '#7f2704'),
    'red':    ('#fee0d2', '#fb6a4a', '#67000d'),
    'purple': ('#efedf5', '#9e9ac8', '#3f007d'),
}
METHODS = {
    'jenks': QgsClassificationJenks,
    'quantile': QgsClassificationQuantile,
    'equal': QgsClassificationEqualInterval,
}


# =====================================================================
# 함수
# =====================================================================
def get_layer(name):
    """프로젝트에서 레이어를 찾고, 없으면 DATA_DIR의 shp를 불러온다."""
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


def apply_graduated_style(layer, field):
    light, mid, dark = COLOR_SCHEMES[COLOR]
    ramp = QgsGradientColorRamp(QColor(light), QColor(dark), False, [QgsGradientStop(0.5, QColor(mid))])

    method = METHODS[METHOD]()
    try:
        method.setLabelPrecision(0)   # 개수(정수)라서 범례에 소수점 제거
    except AttributeError:
        pass

    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute(field)
    renderer.setSourceSymbol(QgsFillSymbol.createSimple({
        'color': '#cccccc', 'outline_color': '#4b5563', 'outline_width': '0.3'}))
    renderer.setClassificationMethod(method)
    renderer.updateClasses(layer, N_CLASSES)
    renderer.updateColorRamp(ramp)
    layer.setRenderer(renderer)


def apply_labels(layer):
    count_ref = QgsExpression.quotedColumnRef(COUNT_FIELD)
    name_ref = QgsExpression.quotedColumnRef(NAME_FIELD)
    settings = QgsPalLayerSettings()
    settings.fieldName = "{} || '\\n' || {}".format(name_ref, count_ref)
    settings.isExpression = True

    text_format = QgsTextFormat()
    text_format.setSize(9)
    text_format.setColor(QColor('#111827'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor('#ffffff'))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


# =====================================================================
# 실행
# =====================================================================
district_layer = get_layer(DISTRICT_LAYER_NAME)
shelter_layer = get_layer(SHELTER_LAYER_NAME)

print('[입력] 구 {}개 / 쉼터 {}곳'.format(district_layer.featureCount(), shelter_layer.featureCount()))
print('[입력] 구 CRS: {} / 쉼터 CRS: {}'.format(district_layer.crs().authid(), shelter_layer.crs().authid()))

# 같은 이름의 이전 결과 레이어가 있으면 제거 (재실행 대비)
for old in QgsProject.instance().mapLayersByName(RESULT_LAYER_NAME):
    QgsProject.instance().removeMapLayer(old.id())

# 1) 구별 포인트 개수 계산
result = processing.run('native:countpointsinpolygon', {
    'POLYGONS': district_layer,
    'POINTS': shelter_layer,
    'WEIGHT': '',
    'CLASSFIELD': '',
    'FIELD': COUNT_FIELD,
    'OUTPUT': 'memory:' + RESULT_LAYER_NAME,
})
result_layer = result['OUTPUT']
result_layer.setName(RESULT_LAYER_NAME)
QgsProject.instance().addMapLayer(result_layer)

# 2) 단계구분도 + 라벨
apply_graduated_style(result_layer, COUNT_FIELD)
if SHOW_LABELS:
    apply_labels(result_layer)
result_layer.triggerRepaint()

# 3) 결과 검증 출력 (리포트 교차검증용)
rows = sorted(
    ((f[NAME_FIELD], int(f[COUNT_FIELD] or 0)) for f in result_layer.getFeatures()),
    key=lambda r: (-r[1], r[0]),
)
print('\n--- 구별 기후동행쉼터 개수 (많은 순) ---')
for name, cnt in rows:
    print('  {:<6} {:>3}  {}'.format(name, cnt, '■' * cnt))
total = sum(c for _, c in rows)
print('합계: {} (입력 쉼터 {}곳)'.format(total, shelter_layer.featureCount()))
if total != shelter_layer.featureCount():
    print('※ 구 경계 밖이거나 좌표계가 다른 쉼터가 있습니다. 위 두 CRS를 확인하세요.')

# 4) 결과 레이어로 화면 이동 (콘솔에서 실행한 경우)
try:
    iface.setActiveLayer(result_layer)
    iface.zoomToActiveLayer()
except NameError:
    pass
