# -*- coding: utf-8 -*-
"""
shp 3개(서울_구, 서울_도로, 서울시_기후동행쉼터) -> 웹 앱용 JSON 3개

사용법:
    python tools/build_data.py <shp가 들어있는 폴더> [출력폴더=docs/data]

- 좌표는 원본 그대로 EPSG:5186(미터)를 쓰고, 정수 밀리미터로 저장한다.
  (거리 계산을 QGIS와 똑같이 미터 단위 평면좌표에서 하기 위함. 지도 표시용 경위도 변환은 브라우저에서 한다.)
- 선/면 좌표는 [x0, y0, dx1, dy1, ...] 형태(첫 점만 절대값, 이후는 이전 점과의 차이)로 저장해 용량을 줄인다.
- 도로/쉼터의 배열 순서(인덱스) = shp 레코드 순서 = QGIS 의 $id.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shp_reader import read_dbf, read_shp  # noqa: E402

DISTRICT = '서울_구'
ROAD = '서울_도로'
SHELTER = '서울시_기후동행쉼터'


def encode_flat(points):
    """[(x, y), ...](m) -> 정수 mm 델타 인코딩 리스트."""
    out, px, py = [], 0, 0
    for i, (x, y) in enumerate(points):
        ix, iy = round(x * 1000), round(y * 1000)
        out.extend([ix, iy] if i == 0 else [ix - px, iy - py])
        px, py = ix, iy
    return out


def dump(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    print('  %-14s %8.2f MB' % (os.path.basename(path), os.path.getsize(path) / 1e6))


def main(src, out):
    os.makedirs(out, exist_ok=True)

    # --- 구 ---------------------------------------------------------------
    rows = read_dbf(os.path.join(src, DISTRICT + '.dbf'))
    geoms = read_shp(os.path.join(src, DISTRICT + '.shp'))
    districts, sig_to_name = [], {}
    for row, parts in zip(rows, geoms):
        code = row['BJCD'][:5]
        sig_to_name[code] = row['NAME']
        districts.append({'name': row['NAME'], 'code': code, 'rings': [encode_flat(p) for p in parts]})
    dump({'crs': 'EPSG:5186', 'unit': 'mm', 'districts': districts}, os.path.join(out, 'districts.json'))

    # --- 쉼터 -------------------------------------------------------------
    rows = read_dbf(os.path.join(src, SHELTER + '.dbf'))
    geoms = read_shp(os.path.join(src, SHELTER + '.shp'))
    keys = list(rows[0].keys())          # dbf 필드명이 10바이트로 잘려 있어 이름 대신 순서로 접근
    k_brand, k_name, k_gu, k_addr, k_hours = keys[1], keys[2], keys[3], keys[4], keys[7]
    shelters = []
    for i, (row, (x, y)) in enumerate(zip(rows, geoms)):
        shelters.append([i, row[k_brand], row[k_name], row[k_gu], row[k_addr], row[k_hours],
                         round(x, 3), round(y, 3)])
    dump({'crs': 'EPSG:5186', 'fields': ['id', 'brand', 'name', 'gu', 'addr', 'hours', 'x', 'y'],
          'rows': shelters}, os.path.join(out, 'shelters.json'))

    # --- 도로 -------------------------------------------------------------
    rows = read_dbf(os.path.join(src, ROAD + '.dbf'))
    geoms = read_shp(os.path.join(src, ROAD + '.shp'))
    names, name_idx = [], {}
    sigs, sig_idx = [], {}
    roads = []
    for row, parts in zip(rows, geoms):
        rn = row['RN']
        if rn not in name_idx:
            name_idx[rn] = len(names)
            names.append(rn)
        sg = row['SIG_CD']
        if sg not in sig_idx:
            sig_idx[sg] = len(sigs)
            sigs.append(sg)
        roads.append([name_idx[rn], sig_idx[sg], float(row['ROAD_LT'] or 0), float(row['ROAD_BT'] or 0),
                      [encode_flat(p) for p in parts]])
    dump({'crs': 'EPSG:5186', 'unit': 'mm', 'names': names,
          'sigs': [[s, sig_to_name.get(s, s)] for s in sigs],
          'fields': ['nameIdx', 'sigIdx', 'length_m', 'width_m', 'parts'], 'roads': roads},
         os.path.join(out, 'roads.json'))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join('docs', 'data'))
