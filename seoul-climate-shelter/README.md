# 서울 기후동행쉼터 공간분석

서울 구 경계, 도로, 기후동행쉼터(KT · CU · 신한은행) 3개 레이어로 만든 공간분석입니다.
같은 분석을 **QGIS(PyQGIS 스크립트 · Processing 플러그인)** 와 **웹(GitHub Pages)** 두 가지로 제공합니다.

| 분석 | 내용 |
|---|---|
| ① 구별 쉼터 개수 | 구 경계 안의 쉼터 개수를 세어 단계구분도로 표시 (적으면 연하게, 많으면 진하게) |
| ② 가까운 쉼터 찾기 | 도로를 선택하면 그 도로에서 가장 가까운 쉼터 N곳(기본 5)을 표시. **브랜드(KT/CU/신한은행) 선택 가능** |

> 웹 앱은 PyQGIS 코드를 브라우저에서 실행하는 것이 아니라, 같은 분석을 JavaScript로 다시 구현한 것입니다.
> 결과가 같은지는 `tests/`의 자동 검증으로 확인합니다. (아래 "검증")

## 1. 웹에서 실행 (GitHub Pages)

배포 후 주소: `https://<GitHub아이디>.github.io/<저장소이름>/`

### 배포 방법
1. GitHub에서 **public** 저장소를 만든다. (무료 Pages는 public 저장소만 지원)
2. 이 폴더의 내용을 올린다.
   - 명령어: 
     ```bash
     git init -b main
     git add .
     git commit -m "서울 기후동행쉼터 공간분석"
     git remote add origin https://github.com/<GitHub아이디>/<저장소이름>.git
     git push -u origin main
     ```
   - 또는 저장소 페이지 > **Add file > Upload files** 로 폴더 안의 파일/폴더를 끌어다 놓기
     (가장 큰 파일 `docs/data/roads.json`이 약 10MB라 웹 업로드 한도 25MB 안에 들어옵니다)
3. 저장소 **Settings > Pages > Build and deployment**
   - Source: `Deploy from a branch`
   - Branch: `main` / 폴더 `/docs` > Save
4. 1~2분 뒤 위 주소로 접속

### 내 컴퓨터에서 실행
`index.html`을 더블클릭(file://)하면 데이터를 읽을 수 없습니다. 웹 서버로 여세요.
```bash
cd docs
python -m http.server 8000      # 브라우저에서 http://localhost:8000
```

### 사용법
- **① 구별 쉼터 개수**: 단계 수 · 분류 방법(Jenks/분위수/등간격) · 색상을 바꿔 볼 수 있고, 구 이름과 개수 라벨, 범례, 순위표, CSV 저장을 지원합니다.
- **② 가까운 쉼터 찾기**: 지도를 14단계 이상 확대하면 도로가 보입니다. 도로를 클릭하고, 브랜드 체크박스(또는 **"만"** 버튼)와 개수를 고르세요.
  브랜드를 `CU`만 고르면 CU 쉼터 안에서만 가까운 곳을 찾습니다.
- 상태는 주소 해시에 저장되어 공유할 수 있습니다. 예: `#tab=nearest&road=0&brands=CU`

## 2. QGIS에서 실행

### PyQGIS 스크립트 (`pyqgis/`)
QGIS > 플러그인 > 파이썬 콘솔 > 스크립트 편집기에서 열어 실행합니다. 프로젝트에 `서울_구`, `서울_도로`, `서울시_기후동행쉼터` 레이어가 있어야 합니다.
- `analysis1_shelter_count_by_district.py` : 구별 개수 + 단계구분도
- `analysis2_nearest5_shelters.py` : 도로를 선택하면 가까운 쉼터 5곳 표시(자동 갱신).
  브랜드는 설정 `BRANDS = ['CU']` 또는 콘솔에서 `set_brands('CU')`, `set_brands()`(전체), `choose_brand()`(선택 창)

### Processing 플러그인 (`qgis_plugin/seoul_climate_shelter/`)
`docs/downloads/seoul_climate_shelter_plugin.zip` 을 QGIS > 플러그인 > 플러그인 관리 및 설치 > ZIP에서 설치.
Processing Toolbox > **서울 기후동행쉼터** 그룹에 도구 2개가 생깁니다.
(`metadata.txt`의 `author`, `email`은 예시 값이니 본인 정보로 바꾸세요.)

## 3. 데이터와 좌표계
- 세 레이어 모두 EPSG:5186 (Korea 2000 / Central Belt 2010, 미터 단위)
- 웹 앱도 거리 계산을 EPSG:5186 평면좌표에서 하고, 지도 표시용으로만 경위도로 변환합니다. (`docs/js/geo.js`)
- `docs/data/*.json` 은 원본 shp에서 `tools/build_data.py` 로 만든 파일입니다. 원본 shp는 이 저장소에 포함하지 않았습니다.
  ```bash
  python tools/build_data.py <shp가 있는 폴더> docs/data
  python tools/make_expected.py <shp가 있는 폴더> tests/expected.json
  ```
- 쉼터의 `쉼터_구` 필드는 구 이름이 아니라 **브랜드**입니다. 구 이름은 `구이름` 필드입니다.
- 공개 저장소에 올리기 전에 원본 데이터의 이용 조건(출처 표기, 재배포 가능 여부)을 확인하세요.

## 4. 검증
파이썬이 shp 원본 좌표로 따로 계산한 기대값(`tests/expected.json`, 정리본 `검증용_기대값.md`)과 비교합니다.

| 명령 | 내용 | 결과 |
|---|---|---|
| `node tests/test_analysis.js` | 웹 계산 모듈: 구별 개수 25개, Jenks 최적해, 브랜드 조건 포함 가까운 5곳 27케이스, 클릭 → 도로 검색, 좌표 변환 | 161 통과 |
| `python tests/pyqgis_console_test.py` | 가짜 QGIS로 콘솔 스크립트 실행: 선택 → 결과, `set_brands`, 연결선, 자동 갱신 해제 | 38 통과 |
| `python tests/ui_smoke_test.py` | Chromium + Leaflet 대역으로 화면 로직: 탭, 범례, 브랜드 선택, CSV, URL 해시 | 62 통과 |

검증하지 않은 것: QGIS API 자체의 동작(`QgsGeometry.distance` 등), 지도 타일과 실제 Leaflet 렌더링.
QGIS 또는 실제 브라우저에서 한 번 실행해 `검증용_기대값.md`의 값과 비교해 확인하세요.
(`ui_smoke_test.py`는 `pip install playwright && playwright install chromium` 이 필요합니다.)

## 5. 한계
- 거리는 도로선에서 쉼터까지의 **직선거리**입니다. 도로망을 따라 걷는 거리가 아닙니다.
- 브랜드 조건을 걸면 해당 브랜드가 적을 때(예: CU 16곳) 가장 가까운 곳도 수 km 떨어질 수 있습니다.
- 웹에서 도로는 14단계 이상 확대해야 그려지고, 처음 접속 시 도로 데이터(약 10MB, 전송 시 압축되어 약 4MB)를 내려받습니다.

## 폴더 구조
```
docs/            웹 앱 (GitHub Pages 소스)  index.html, js/, css/, data/, downloads/
pyqgis/          콘솔용 PyQGIS 스크립트 2개
qgis_plugin/     Processing 플러그인 소스
tools/           shp 리더, 데이터/기대값 생성기
tests/           자동 검증 (JS, 콘솔 스크립트, UI)
```
