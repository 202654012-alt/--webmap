# -*- coding: utf-8 -*-
"""
기대값(tests/expected.json) 생성기.

웹 앱의 JavaScript 분석 결과를 검증하기 위해, JS와 별개로 shp 원본(실수 좌표)에서
파이썬으로 직접 계산한다. (QGIS 결과와 비교할 때도 이 값을 쓸 수 있다.)

  1) 구별 쉼터 개수 (점이 구 폴리곤 안에 있는지)
  2) 자연 구간(Jenks) / 분위수 / 등간격 경계값  (Jenks는 전수 탐색으로 최적해를 구함)
  3) 도로 -> 가장 가까운 쉼터 K곳 (브랜드 조건 포함)
  4) 지도 클릭 지점 -> 가장 가까운 도로

사용법:
    python tools/make_expected.py <shp가 들어있는 폴더> [출력파일=tests/expected.json]
"""
import itertools
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shp_reader import point_in_rings, point_to_polyline, read_dbf, read_shp  # noqa: E402


def jenks_bruteforce(values, k):
    """고유값 단위로 모든 분할을 전수 탐색해 클래스 내 제곱합이 최소인 분할(들)의 상한 경계를 반환."""
    vals = sorted(values)
    uniq = sorted(set(vals))
    weight = [vals.count(u) for u in uniq]
    m = len(uniq)
    k = min(k, m)

    def sse(i, j):  # uniq[i..j] 포함
        w = sum(weight[i:j + 1])
        s = sum(weight[t] * uniq[t] for t in range(i, j + 1))
        s2 = sum(weight[t] * uniq[t] ** 2 for t in range(i, j + 1))
        return s2 - s * s / w

    best, best_sets = float('inf'), []
    for cuts in itertools.combinations(range(1, m), k - 1):   # cut = 새 클래스가 시작하는 위치
        starts = (0,) + cuts
        ends = tuple(c - 1 for c in cuts) + (m - 1,)
        total = sum(sse(a, b) for a, b in zip(starts, ends))
        if total < best - 1e-9:
            best, best_sets = total, [[uniq[e] for e in ends]]
        elif abs(total - best) <= 1e-9:
            best_sets.append([uniq[e] for e in ends])
    return {'k': k, 'sse': best, 'optimalBreaks': best_sets}


def quantile_breaks(values, k):
    v = sorted(values)
    n = len(v)
    out = []
    for i in range(1, k):
        h = (n - 1) * i / k
        lo = int(math.floor(h))
        out.append(v[lo] + (h - lo) * (v[min(lo + 1, n - 1)] - v[lo]))
    out.append(v[-1])
    return out


def equal_breaks(values, k):
    lo, hi = min(values), max(values)
    return [lo + (hi - lo) * i / k for i in range(1, k)] + [hi]


def main(src, out_path):
    rd = lambda n: (read_dbf(os.path.join(src, n + '.dbf')), read_shp(os.path.join(src, n + '.shp')))
    gu_rows, gu_geom = rd('서울_구')
    sh_rows, sh_geom = rd('서울시_기후동행쉼터')
    road_rows, road_geom = rd('서울_도로')
    keys = list(sh_rows[0].keys())
    k_brand, k_name = keys[1], keys[2]
    brands = [r[k_brand] for r in sh_rows]
    names = [r[k_name] for r in sh_rows]

    # 1) 구별 개수 ---------------------------------------------------------
    counts = {r['NAME']: 0 for r in gu_rows}
    for p in sh_geom:
        for r, rings in zip(gu_rows, gu_geom):
            if point_in_rings(p, rings):
                counts[r['NAME']] += 1
                break
    brand_totals = {}
    for b in brands:
        brand_totals[b] = brand_totals.get(b, 0) + 1

    # 2) 분류 경계 ---------------------------------------------------------
    vals = list(counts.values())
    classification = {
        'values': sorted(vals),
        'jenks': {str(k): jenks_bruteforce(vals, k) for k in range(3, 8)},
        'quantile': {str(k): quantile_breaks(vals, k) for k in range(3, 8)},
        'equal': {str(k): equal_breaks(vals, k) for k in range(3, 8)},
    }

    # 3) 도로 -> 가까운 쉼터 --------------------------------------------------
    rng = random.Random(20261022)
    road_ids = [0]
    road_ids += [i for i, r in enumerate(road_rows) if r['RN'] in ('테헤란로', '세종대로')][:1]
    for target in ('테헤란로', '세종대로'):
        road_ids.append(next(i for i, r in enumerate(road_rows) if r['RN'] == target))
    road_ids += rng.sample(range(len(road_rows)), 8)
    road_ids = list(dict.fromkeys(road_ids))
    brand_cases = [None, ['CU'], ['KT'], ['신한은행'], ['CU', 'KT']]

    nearest = []
    for n, rid in enumerate(road_ids):
        for bs in (brand_cases if n < 4 else [brand_cases[n % len(brand_cases)]]):
            cand = []
            for i, p in enumerate(sh_geom):
                if bs is not None and brands[i] not in bs:
                    continue
                cand.append((point_to_polyline(p, road_geom[rid]), i))
            cand.sort()
            nearest.append({
                'roadId': rid, 'roadName': road_rows[rid]['RN'], 'brands': bs, 'k': 5,
                'results': [{'id': i, 'name': names[i], 'brand': brands[i], 'dist': d} for d, i in cand[:5]],
            })

    # 4) 클릭 지점 -> 가장 가까운 도로 ---------------------------------------
    bbox = []
    for parts in road_geom:
        xs = [p[0] for part in parts for p in part]
        ys = [p[1] for part in parts for p in part]
        bbox.append((min(xs), min(ys), max(xs), max(ys)))
    clicks = []
    for rid in rng.sample(range(len(road_rows)), 6):
        part = road_geom[rid][0]
        (x1, y1), (x2, y2) = part[0], part[1] if len(part) > 1 else part[0]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        L = math.hypot(x2 - x1, y2 - y1) or 1.0
        px, py = mx - (y2 - y1) / L * 4.0, my + (x2 - x1) / L * 4.0      # 도로에서 수직으로 4m 떨어진 점
        best = (float('inf'), -1)
        for i, (bx0, by0, bx1, by1) in enumerate(bbox):
            if bx0 - 100 <= px <= bx1 + 100 and by0 - 100 <= py <= by1 + 100:
                d = point_to_polyline((px, py), road_geom[i])
                if (d, i) < best:
                    best = (d, i)
        clicks.append({'x': px, 'y': py, 'roadId': best[1], 'dist': best[0]})

    expected = {
        'districtCounts': counts, 'brandTotals': brand_totals, 'totalShelters': len(sh_geom),
        'classification': classification, 'nearest': nearest, 'nearestRoad': clicks,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(expected, f, ensure_ascii=False, indent=1)
    print('기대값 저장:', out_path, '| 근접 쉼터 케이스', len(nearest), '| 클릭 케이스', len(clicks))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join('tests', 'expected.json'))
