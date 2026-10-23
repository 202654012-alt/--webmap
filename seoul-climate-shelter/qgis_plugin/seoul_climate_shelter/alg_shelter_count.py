# -*- coding: utf-8 -*-
from qgis import processing
from qgis.core import (
    QgsExpression,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingUtils,
)

from .common import (
    COLOR_NAMES,
    METHOD_NAMES,
    StylePostProcessor,
    apply_graduated_style,
    apply_labels,
    integer_number_type,
    source_type,
)


class ShelterCountByDistrictAlgorithm(QgsProcessingAlgorithm):
    """구(폴리곤)별 기후동행쉼터(포인트) 개수를 세고 단계구분도로 표시한다."""

    DISTRICT = 'DISTRICT'
    SHELTER = 'SHELTER'
    NAME_FIELD = 'NAME_FIELD'
    CLASSES = 'CLASSES'
    METHOD = 'METHOD'
    COLOR = 'COLOR'
    LABELS = 'LABELS'
    OUTPUT = 'OUTPUT'

    COUNT_FIELD = 'shelter_cnt'

    def createInstance(self):
        return ShelterCountByDistrictAlgorithm()

    def name(self):
        return 'shelter_count_by_district'

    def displayName(self):
        return '구별 기후동행쉼터 개수 단계구분도'

    def group(self):
        return '기후동행쉼터 분석'

    def groupId(self):
        return 'climate_shelter'

    def shortHelpString(self):
        return (
            '구 경계(폴리곤) 안에 있는 기후동행쉼터(포인트) 개수를 세어 '
            '<b>shelter_cnt</b> 필드로 저장하고, 개수가 적은 구는 연하게 · 많은 구는 진하게 '
            '단계구분도(Graduated)로 표시합니다.<br><br>'
            '- 분류 방법: 자연 구간(Jenks) / 분위수 / 등간격<br>'
            '- 색상: 값이 클수록 진해지는 단일 색상 계열<br>'
            '- 처리 로그에 구별 개수 순위표가 출력되며, 구 경계 밖에 있는 쉼터가 있으면 경고합니다.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.DISTRICT, '구 경계 레이어 (폴리곤)', [source_type('polygon')]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SHELTER, '기후동행쉼터 레이어 (포인트)', [source_type('point')]))
        self.addParameter(QgsProcessingParameterField(
            self.NAME_FIELD, '구 이름 필드 (라벨 표시용)', defaultValue='NAME',
            parentLayerParameterName=self.DISTRICT, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CLASSES, '단계(클래스) 수', type=integer_number_type(),
            defaultValue=5, minValue=2, maxValue=9))
        self.addParameter(QgsProcessingParameterEnum(
            self.METHOD, '분류 방법', options=METHOD_NAMES, defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.COLOR, '색상 계열', options=COLOR_NAMES, defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.LABELS, '구 이름과 개수를 라벨로 표시', defaultValue=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, '구별 기후동행쉼터 개수', type=source_type('polygon')))

    def processAlgorithm(self, parameters, context, feedback):
        district = self.parameterAsSource(parameters, self.DISTRICT, context)
        shelter = self.parameterAsSource(parameters, self.SHELTER, context)
        if district is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.DISTRICT))
        if shelter is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.SHELTER))

        n_classes = self.parameterAsInt(parameters, self.CLASSES, context)
        method_index = self.parameterAsEnum(parameters, self.METHOD, context)
        color_index = self.parameterAsEnum(parameters, self.COLOR, context)
        show_labels = self.parameterAsBool(parameters, self.LABELS, context)
        name_field = self.parameterAsString(parameters, self.NAME_FIELD, context)
        if name_field and district.fields().lookupField(name_field) < 0:
            feedback.pushWarning("구 이름 필드 '{}'를 찾을 수 없어 개수만 라벨로 표시합니다.".format(name_field))
            name_field = ''

        # 1) 구별 포인트 개수 계산 (QGIS 기본 알고리즘 사용, 결과를 이 알고리즘의 출력으로 그대로 전달)
        feedback.pushInfo('구별 쉼터 개수를 계산합니다...')
        result = processing.run(
            'native:countpointsinpolygon',
            {
                'POLYGONS': parameters[self.DISTRICT],
                'POINTS': parameters[self.SHELTER],
                'WEIGHT': '',
                'CLASSFIELD': '',
                'FIELD': self.COUNT_FIELD,
                'OUTPUT': parameters[self.OUTPUT],
            },
            context=context, feedback=feedback, is_child_algorithm=True,
        )
        dest_id = result['OUTPUT']

        # 2) 결과 요약을 처리 로그에 출력 (리포트 교차검증용)
        try:
            out_layer = QgsProcessingUtils.mapLayerFromString(dest_id, context)
            if out_layer is not None:
                rows = []
                for feat in out_layer.getFeatures():
                    label = feat[name_field] if name_field else str(feat.id())
                    rows.append((label, int(feat[self.COUNT_FIELD] or 0)))
                rows.sort(key=lambda r: (-r[1], str(r[0])))
                feedback.pushInfo('--- 구별 기후동행쉼터 개수 (많은 순) ---')
                for label, cnt in rows:
                    feedback.pushInfo('  {}: {}'.format(label, cnt))
                total = sum(c for _, c in rows)
                feedback.pushInfo('합계: {}'.format(total))
                n_shelters = shelter.featureCount()
                if n_shelters >= 0 and total != n_shelters:
                    feedback.pushWarning(
                        '쉼터 {}곳 중 {}곳만 구 경계 안에서 집계되었습니다. '
                        '(경계 밖이거나 좌표계가 다른 점이 있는지 확인하세요)'.format(n_shelters, total))
        except Exception as exc:
            feedback.pushWarning('요약 출력 중 오류(결과에는 영향 없음): {}'.format(exc))

        # 3) 프로젝트에 로드될 때 단계구분도 + 라벨 스타일 적용
        count_field = self.COUNT_FIELD

        def style(layer):
            apply_graduated_style(layer, count_field, n_classes, method_index, color_index)
            if show_labels:
                count_ref = QgsExpression.quotedColumnRef(count_field)
                if name_field:
                    expr = "{} || '\\n' || {}".format(QgsExpression.quotedColumnRef(name_field), count_ref)
                else:
                    expr = count_ref
                apply_labels(layer, expr)
            layer.triggerRepaint()

        if context.willLoadLayerOnCompletion(dest_id):
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(
                StylePostProcessor.create(style))

        return {self.OUTPUT: dest_id}
