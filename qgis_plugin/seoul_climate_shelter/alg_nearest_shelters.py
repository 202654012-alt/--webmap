# -*- coding: utf-8 -*-
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsFields,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from .common import (
    StylePostProcessor,
    apply_labels,
    apply_result_point_style,
    integer_number_type,
    make_field,
    source_type,
)


class NearestSheltersAlgorithm(QgsProcessingAlgorithm):
    """선택한 도로 객체에서 가장 가까운 기후동행쉼터 N곳을 새 포인트 레이어로 만든다."""

    ROAD = 'ROAD'
    SHELTER = 'SHELTER'
    K = 'K'
    BRAND_FIELD = 'BRAND_FIELD'
    BRAND_VALUES = 'BRAND_VALUES'
    ROAD_NAME_FIELD = 'ROAD_NAME_FIELD'
    OUTPUT = 'OUTPUT'

    MAX_ROADS = 20  # 선택 없이 전체 도로(수만 개)를 실수로 돌리는 것을 막는 안전장치

    def createInstance(self):
        return NearestSheltersAlgorithm()

    def name(self):
        return 'nearest_shelters_from_road'

    def displayName(self):
        return '선택한 도로에서 가까운 기후동행쉼터 찾기'

    def group(self):
        return '기후동행쉼터 분석'

    def groupId(self):
        return 'climate_shelter'

    def shortHelpString(self):
        return (
            '도로 레이어에서 <b>객체를 선택</b>한 뒤 실행하면, 선택한 도로에서 가장 가까운 '
            '기후동행쉼터 N곳(기본 5곳)을 새 포인트 레이어로 만듭니다.<br><br>'
            '<b>사용 방법</b><br>'
            '1. 지도에서 \'객체 선택\' 도구로 도로 하나(또는 몇 개)를 선택합니다.<br>'
            '2. 이 도구를 열고 도로 레이어 오른쪽의 <b>\'선택한 피처만\'</b>에 체크합니다.<br>'
            '3. 실행하면 결과 레이어가 추가됩니다. (rank=거리순위, dist_m=도로까지 거리(m))<br><br>'
            '<b>브랜드 선택</b><br>'
            '- \'대상 브랜드\'에 <b>CU</b> 또는 <b>CU,KT</b> 처럼 쉼표로 적으면 그 브랜드 쉼터 안에서만 가까운 곳을 찾습니다.<br>'
            '- 비워두면 전체 브랜드입니다. 쉼터 레이어에 있는 브랜드 목록과 개수는 처리 로그에 출력됩니다.<br><br>'
            '<b>참고</b><br>'
            '- 거리는 도로선(전체 선형)에서 쉼터까지의 <b>직선거리</b>입니다. 도로망을 따라 걷는 거리가 아닙니다.<br>'
            '- 도로 레이어는 미터 단위 투영좌표계여야 합니다 (예: EPSG:5186).<br>'
            '- 한 번에 최대 {}개의 도로까지 처리합니다.'.format(self.MAX_ROADS)
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROAD, '도로 레이어 (선) - 객체를 먼저 선택하세요', [source_type('line')]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SHELTER, '기후동행쉼터 레이어 (포인트)', [source_type('point')]))
        self.addParameter(QgsProcessingParameterNumber(
            self.K, '찾을 쉼터 개수', type=integer_number_type(),
            defaultValue=5, minValue=1, maxValue=50))
        self.addParameter(QgsProcessingParameterField(
            self.BRAND_FIELD, '쉼터 브랜드(구분) 필드', defaultValue='쉼터_구',
            parentLayerParameterName=self.SHELTER, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.BRAND_VALUES, '대상 브랜드 (쉼표로 구분, 비우면 전체)  예) CU  /  CU,KT',
            defaultValue='', optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ROAD_NAME_FIELD, '도로 이름 필드 (결과에 기록)', defaultValue='RN',
            parentLayerParameterName=self.ROAD, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, '가까운 기후동행쉼터', type=source_type('point')))

    @staticmethod
    def _guess_name_field(fields):
        for candidate in ('쉼터명', 'NAME', 'name', '이름'):
            if fields.lookupField(candidate) >= 0:
                return candidate
        return None

    def processAlgorithm(self, parameters, context, feedback):
        road_src = self.parameterAsSource(parameters, self.ROAD, context)
        shelter_src = self.parameterAsSource(parameters, self.SHELTER, context)
        if road_src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.ROAD))
        if shelter_src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.SHELTER))

        k = self.parameterAsInt(parameters, self.K, context)
        road_name_field = self.parameterAsString(parameters, self.ROAD_NAME_FIELD, context)
        if road_name_field and road_src.fields().lookupField(road_name_field) < 0:
            road_name_field = ''

        road_crs = road_src.sourceCrs()
        if road_crs.isGeographic():
            raise QgsProcessingException(
                '도로 레이어가 경위도(도 단위) 좌표계입니다. 거리를 미터로 계산하려면 '
                '미터 단위 투영좌표계(예: EPSG:5186)의 레이어를 사용하세요.')

        # 1) 선택된 도로 읽기 (선택이 없거나 너무 많으면 친절하게 중단)
        roads = []
        for feat in road_src.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                roads.append(feat)
            if len(roads) > self.MAX_ROADS:
                raise QgsProcessingException(
                    '도로 객체가 {}개를 넘습니다. 지도에서 도로를 먼저 선택하고, 입력 레이어의 '
                    '"선택한 피처만"에 체크한 뒤 다시 실행하세요.'.format(self.MAX_ROADS))
        if not roads:
            raise QgsProcessingException(
                '처리할 도로 객체가 없습니다. 지도에서 도로를 먼저 선택하고, 입력 레이어의 '
                '"선택한 피처만"에 체크한 뒤 다시 실행하세요.')

        # 2) 쉼터를 도로 좌표계로 맞춰서 읽기
        request = QgsFeatureRequest().setDestinationCrs(road_crs, context.transformContext())
        shelters = [f for f in shelter_src.getFeatures(request)
                    if f.hasGeometry() and not f.geometry().isEmpty()]
        if not shelters:
            raise QgsProcessingException('쉼터 레이어에 유효한 포인트가 없습니다.')

        # 2-1) 브랜드 조건 (예: CU 만)
        brand_field = self.parameterAsString(parameters, self.BRAND_FIELD, context)
        brand_text = self.parameterAsString(parameters, self.BRAND_VALUES, context)
        wanted = [b.strip() for b in brand_text.replace('，', ',').split(',') if b.strip()]
        has_brand_field = bool(brand_field) and shelter_src.fields().lookupField(brand_field) >= 0
        if has_brand_field:
            brand_counts = {}
            for s in shelters:
                key = str(s[brand_field]).strip()
                brand_counts[key] = brand_counts.get(key, 0) + 1
            summary = ', '.join('{} {}곳'.format(b, n) for b, n in sorted(brand_counts.items(), key=lambda kv: -kv[1]))
            feedback.pushInfo('쉼터 브랜드 현황 ({}): {}'.format(brand_field, summary))
        if wanted:
            if not has_brand_field:
                raise QgsProcessingException(
                    "브랜드 필드 '{}'를 쉼터 레이어에서 찾을 수 없습니다. 필드를 확인하세요.".format(brand_field))
            known = {b.casefold() for b in brand_counts}
            unknown = [w for w in wanted if w.casefold() not in known]
            if unknown:
                raise QgsProcessingException(
                    "브랜드 '{}'를 찾을 수 없습니다. 사용 가능한 값: {}".format(', '.join(unknown), ', '.join(sorted(brand_counts))))
            wanted_keys = {w.casefold() for w in wanted}
            shelters = [s for s in shelters if str(s[brand_field]).strip().casefold() in wanted_keys]
            feedback.pushInfo('브랜드 조건: {} -> 대상 쉼터 {}곳'.format(', '.join(wanted), len(shelters)))
            if len(shelters) < k:
                feedback.pushWarning('대상 쉼터가 {}곳뿐이라 {}곳만 표시됩니다.'.format(len(shelters), len(shelters)))

        # 3) 출력 필드 = 쉼터 원본 필드 + 순위/거리/도로 정보
        fields = QgsFields()
        for field in shelter_src.fields():
            fields.append(field)
        fields.append(make_field('rank', 'int'))
        fields.append(make_field('dist_m', 'double', 20, 3))
        fields.append(make_field('road_fid', 'int'))
        fields.append(make_field('road_name', 'string', 254))

        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, shelter_src.wkbType(), road_crs)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        # 4) 도로별로 가장 가까운 쉼터 k곳 계산
        name_field = self._guess_name_field(shelter_src.fields())
        total = len(roads)
        for i, road in enumerate(roads):
            if feedback.isCanceled():
                break
            road_geom = road.geometry()
            road_name = str(road[road_name_field]) if road_name_field else ''

            scored = sorted(
                ((road_geom.distance(s.geometry()), s.id(), s) for s in shelters),
                key=lambda t: (t[0], t[1]),
            )[:k]

            feedback.pushInfo('[도로 id={} {}] 가장 가까운 쉼터 {}곳'.format(road.id(), road_name, len(scored)))
            for rank, (dist, _, shelter) in enumerate(scored, start=1):
                out = QgsFeature(fields)
                out.setGeometry(shelter.geometry())
                out.setAttributes(list(shelter.attributes()) + [rank, round(dist, 3), road.id(), road_name])
                sink.addFeature(out)
                label = shelter[name_field] if name_field else shelter.id()
                feedback.pushInfo('  {}. {} - {:,.1f} m'.format(rank, label, dist))

            feedback.setProgress(int((i + 1) / total * 100))

        # 5) 프로젝트에 로드될 때 스타일(빨간 점 + 순위 라벨) 적용
        def style(layer):
            apply_result_point_style(layer)
            apply_labels(layer, '"rank"', size=11.0)
            layer.triggerRepaint()

        if context.willLoadLayerOnCompletion(dest_id):
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(
                StylePostProcessor.create(style))

        return {self.OUTPUT: dest_id}
