# -*- coding: utf-8 -*-
"""두 알고리즘이 함께 쓰는 헬퍼 모음 (QGIS 3.28 ~ 3.44 호환)."""
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsClassificationEqualInterval,
    QgsClassificationJenks,
    QgsClassificationQuantile,
    QgsField,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProcessing,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingParameterNumber,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
)


# ----------------------------------------------------------------------
# QGIS 버전 호환 헬퍼
# ----------------------------------------------------------------------
def source_type(kind):
    """'polygon' | 'point' | 'line' -> 입력 레이어 유형 상수."""
    names = {'polygon': 'VectorPolygon', 'point': 'VectorPoint', 'line': 'VectorLine'}
    try:
        from qgis.core import Qgis
        return getattr(Qgis.ProcessingSourceType, names[kind])  # QGIS 3.36+
    except (ImportError, AttributeError):
        return getattr(QgsProcessing, 'Type' + names[kind])      # 이전 버전


def integer_number_type():
    try:
        from qgis.core import Qgis
        return Qgis.ProcessingNumberParameterType.Integer        # QGIS 3.36+
    except (ImportError, AttributeError):
        return QgsProcessingParameterNumber.Integer              # 이전 버전


def make_field(name, kind, length=0, precision=0):
    """kind: 'int' | 'double' | 'string'. QMetaType(3.38+) 우선, 실패하면 QVariant 사용."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        qt_type = {
            'int': QMetaType.Type.Int,
            'double': QMetaType.Type.Double,
            'string': QMetaType.Type.QString,
        }[kind]
        return QgsField(name, qt_type, '', length, precision)
    except (ImportError, AttributeError, TypeError):
        from qgis.PyQt.QtCore import QVariant
        qt_type = {
            'int': QVariant.Int,
            'double': QVariant.Double,
            'string': QVariant.String,
        }[kind]
        return QgsField(name, qt_type, '', length, precision)


# ----------------------------------------------------------------------
# 단계구분도(Graduated) 스타일
# ----------------------------------------------------------------------
METHOD_NAMES = ['자연 구간 (Jenks)', '분위수 (Quantile)', '등간격 (Equal Interval)']

# (이름, 가장 연한 색, 중간 색, 가장 진한 색) : 값이 클수록 진해지는 단일 색상 계열
COLOR_SCHEMES = [
    ('파랑', '#deebf7', '#6baed6', '#08306b'),
    ('초록', '#e5f5e0', '#74c476', '#00441b'),
    ('주황', '#fee6ce', '#fd8d3c', '#7f2704'),
    ('빨강', '#fee0d2', '#fb6a4a', '#67000d'),
    ('보라', '#efedf5', '#9e9ac8', '#3f007d'),
]
COLOR_NAMES = [c[0] for c in COLOR_SCHEMES]


def make_ramp(index):
    _, light, mid, dark = COLOR_SCHEMES[index]
    return QgsGradientColorRamp(
        QColor(light), QColor(dark), False, [QgsGradientStop(0.5, QColor(mid))]
    )


def make_method(index):
    cls = [QgsClassificationJenks, QgsClassificationQuantile, QgsClassificationEqualInterval][index]
    method = cls()
    try:
        method.setLabelPrecision(0)  # 개수(정수)이므로 범례 라벨에 소수점을 붙이지 않는다
    except AttributeError:
        pass
    return method


def apply_graduated_style(layer, field, n_classes, method_index, color_index):
    symbol = QgsFillSymbol.createSimple({
        'color': '#cccccc',
        'outline_color': '#4b5563',
        'outline_width': '0.3',
    })
    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute(field)
    renderer.setSourceSymbol(symbol)
    renderer.setClassificationMethod(make_method(method_index))
    renderer.updateClasses(layer, n_classes)
    renderer.updateColorRamp(make_ramp(color_index))
    layer.setRenderer(renderer)


def apply_labels(layer, expression, size=9.0):
    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = True

    text_format = QgsTextFormat()
    text_format.setSize(size)
    text_format.setColor(QColor('#111827'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor('#ffffff'))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def apply_result_point_style(layer):
    symbol = QgsMarkerSymbol.createSimple({
        'name': 'circle',
        'color': '#dc2626',
        'size': '4',
        'outline_color': '#ffffff',
        'outline_width': '0.6',
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


# ----------------------------------------------------------------------
# 출력 레이어 후처리(스타일 적용)
#   알고리즘 안에서 레이어를 직접 꾸미면 프로젝트에 로드되는 레이어에는 적용되지 않으므로,
#   QGIS 공식 방식인 post-processor로 "프로젝트에 로드된 레이어"에 스타일을 입힌다.
# ----------------------------------------------------------------------
_KEEP_ALIVE = []  # sip 문제 방지: 후처리기 객체가 가비지 컬렉션되지 않도록 참조 유지


class StylePostProcessor(QgsProcessingLayerPostProcessorInterface):

    def __init__(self, style_func):
        super().__init__()
        self._style_func = style_func

    def postProcessLayer(self, layer, context, feedback):
        try:
            self._style_func(layer)
        except Exception as exc:  # 스타일 실패가 분석 결과를 막지 않도록 경고만 남김
            feedback.reportError('스타일 적용 중 오류 (결과 레이어는 정상 생성됨): {}'.format(exc))

    @staticmethod
    def create(style_func):
        instance = StylePostProcessor(style_func)
        _KEEP_ALIVE.append(instance)
        return instance
