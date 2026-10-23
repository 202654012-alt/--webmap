# Seoul Climate Shelter Tools (QGIS Processing 플러그인)

서울 기후동행쉼터 공간분석용 Processing 도구 2개를 Processing Toolbox에 추가합니다.

## 설치
QGIS > 플러그인 > 플러그인 관리 및 설치 > **ZIP에서 설치** > 이 zip 선택 > 설치
(설치 후 "설치됨" 탭에서 *Seoul Climate Shelter Tools* 가 체크되어 있는지 확인)

## 도구 위치
Processing Toolbox(처리 도구상자) > **서울 기후동행쉼터**

### 1. 구별 기후동행쉼터 개수 단계구분도
- 입력: 구 경계(폴리곤), 기후동행쉼터(포인트)
- 출력: 구별 개수(`shelter_cnt`)가 들어간 폴리곤 레이어 + 단계구분도(연함=적음, 진함=많음)
- 옵션: 단계 수, 분류 방법(Jenks/분위수/등간격), 색상 계열, 라벨 표시

### 2. 선택한 도로에서 가까운 기후동행쉼터 찾기
1. 지도에서 **객체 선택** 도구로 도로를 선택
2. 도구 실행 창에서 도로 레이어의 **"선택한 피처만"** 체크
3. 실행 -> 가장 가까운 쉼터 N곳(기본 5)이 새 레이어로 표시 (`rank`, `dist_m` 포함)
4. (선택) **대상 브랜드**에 `CU` 또는 `CU,KT` 처럼 적으면 그 브랜드 쉼터 안에서만 찾습니다. 비우면 전체 브랜드.
   (브랜드 필드는 기본값 `쉼터_구`, 브랜드 목록과 개수는 처리 로그에 출력됩니다)

- 거리는 도로선에서 쉼터까지의 직선거리(m)이며, 도로망 경로 거리가 아닙니다.
- 도로 레이어는 미터 단위 투영좌표계여야 합니다 (예: EPSG:5186).

## 파이썬 콘솔에서 호출 (분석 1)
```python
from qgis import processing
processing.runAndLoadResults('seoul_climate_shelter:shelter_count_by_district', {
    'DISTRICT': '서울_구', 'SHELTER': '서울시_기후동행쉼터',
    'NAME_FIELD': 'NAME', 'CLASSES': 5, 'METHOD': 0, 'COLOR': 0, 'LABELS': True,
    'OUTPUT': 'TEMPORARY_OUTPUT'})
```
