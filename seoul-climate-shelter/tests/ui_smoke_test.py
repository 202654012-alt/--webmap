# -*- coding: utf-8 -*-
"""
UI 스모크 테스트:  python tests/ui_smoke_test.py

네트워크 없이도 돌도록 CDN 의 Leaflet 을 tests/leaflet_shim.js 로 바꿔 끼운 채, 실제 Chromium 에서
docs/index.html 을 열어 화면 로직을 검증한다. (지도 타일/렌더링 자체는 검증 대상이 아님)
필요: pip install playwright  +  playwright install chromium
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
SHIM = open(os.path.join(ROOT, 'tests', 'leaflet_shim.js'), encoding='utf-8').read()
EXPECTED = json.load(open(os.path.join(ROOT, 'tests', 'expected.json'), encoding='utf-8'))

passed, failed = 0, []


def check(cond, msg):
    global passed
    if cond:
        passed += 1
    else:
        failed.append(msg)
        print('  ✗', msg)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_server():
    port = free_port()
    proc = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1', '--directory', DOCS],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/index.html' % port, timeout=1).read(10)
            return proc, port
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError('로컬 서버를 시작하지 못했습니다')


def fmt1(v):
    return '{:,.1f}'.format(v)


def case(road_id, brands):
    return next(c for c in EXPECTED['nearest'] if c['roadId'] == road_id and c['brands'] == brands)


def table_rows(page):
    return page.eval_on_selector_all(
        '#result-table tbody tr',
        'els => els.map(e => [e.children[1].childNodes[0].textContent, e.children[2].textContent, e.children[3].textContent])')


def open_app(browser, port, hash_=''):
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    errors = []
    page.on('pageerror', lambda e: errors.append('pageerror: %s' % e))
    page.on('console', lambda m: errors.append('console.error: %s' % m.text) if m.type == 'error' else None)
    page.route('**/unpkg.com/**', lambda r: r.fulfill(
        status=200, content_type='application/javascript' if r.request.url.endswith('.js') else 'text/css',
        body=SHIM if r.request.url.endswith('.js') else ''))
    page.goto('http://127.0.0.1:%d/index.html%s' % (port, hash_))
    page.wait_for_function('window.SCSApp && document.getElementById("loading").hidden === true', timeout=90000)
    return page, errors


def luminance(hex_color):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    proc, port = start_server()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'))
            run(browser, port)
            browser.close()
    finally:
        proc.kill()
    print('\n결과: 통과 %d / 실패 %d' % (passed, len(failed)))
    sys.exit(1 if failed else 0)


def run(browser, port):
    page, errors = open_app(browser, port)

    # ---------------- 분석 1 ----------------
    print('[UI-1] 구별 쉼터 개수 단계구분도')
    check('412곳' in page.inner_text('#summary'), '요약에 전체 쉼터 412곳 표시')
    legend = page.eval_on_selector_all('#legend li', 'els => els.map(e => e.textContent)')
    check(len(legend) == 5, '범례 5개 (실제 %d)' % len(legend))
    check(legend and legend[0].startswith('7–11곳') and legend[-1].startswith('24–33곳'),
          '범례 범위가 Jenks 경계 [11,15,20,23,33] 와 일치: %s' % legend)
    ranks = page.eval_on_selector_all('#rank-list li', 'els => els.map(e => [e.dataset.name, e.querySelector(".n").textContent])')
    check(len(ranks) == 25 and ranks[0] == ['강남구', '33'] and ranks[-1] == ['금천구', '7'], '순위표 25개, 1위 강남구 33 / 꼴찌 금천구 7')
    check(all(ranks[i][1] == str(EXPECTED['districtCounts'][ranks[i][0]]) for i in range(25)), '순위표 값이 기대값과 일치')

    colors = page.evaluate('SCSApp.polys.map(p => [p.d.name, p.poly.options.fillColor])')
    by_count = sorted(((EXPECTED['districtCounts'][n], c) for n, c in colors), key=lambda t: t[0])
    lum = [luminance(c) for _, c in by_count]
    check(all(lum[i] >= lum[i + 1] - 1e-9 for i in range(len(lum) - 1)), '개수가 많을수록 색이 진해짐(밝기 단조 감소)')
    check(by_count[0][1] == '#deebf7' and by_count[-1][1] == '#08306b', '가장 적은 구=가장 연한 색, 가장 많은 구=가장 진한 색')

    check(page.evaluate('SCSApp.polys.every(p => p.poly._tooltip && p.poly._tooltip.indexOf(p.d.name) === 0)'), '구 이름·개수 라벨 표시')
    page.uncheck('#show-labels')
    check(page.evaluate('SCSApp.polys.every(p => !p.poly._tooltip)'), '라벨 체크 해제 시 라벨 제거')
    page.check('#show-labels')

    page.select_option('#class-count', '3')
    n3 = page.eval_on_selector_all('#legend li', 'els => els.length')
    check(1 <= n3 <= 3, '단계 수 3 -> 범례 %d개' % n3)
    for method in ('quantile', 'equal', 'jenks'):
        page.select_option('#class-method', method)
        check(page.eval_on_selector_all('#legend li', 'els => els.length') >= 1, '분류 방법 %s 범례 생성' % method)
    page.select_option('#class-color', 'red')
    check(page.evaluate('SCSApp.polys.some(p => p.poly.options.fillColor === "#67000d")'), '색상 계열 빨강 적용')
    page.select_option('#class-count', '5')
    page.select_option('#class-color', 'blue')

    with page.expect_download() as dl:
        page.click('#csv-count')
    text = open(dl.value.path(), encoding='utf-8').read()
    check(text.startswith('\ufeff구,기후동행쉼터 개수,단계') and len(text.strip().splitlines()) == 26, 'CSV(구별 개수) 26행, Excel용 BOM 포함')

    # ---------------- 분석 2 ----------------
    print('[UI-2] 도로 선택 -> 가까운 쉼터')
    page.click('#tabbtn-nearest')
    check(page.is_visible('#tab-nearest') and not page.is_visible('#tab-count'), '탭 전환')
    check(page.evaluate('SCSApp.map.hasLayer(SCSApp.layers.roads) && SCSApp.map.hasLayer(SCSApp.layers.shelters)'), '도로·쉼터 레이어 켜짐')
    check(page.is_visible('#zoom-hint'), '확대 전에는 확대 안내 표시')
    check(page.eval_on_selector_all('#brand-list label.brand', 'els => els.length') == 3, '브랜드 체크박스 3개(KT/신한은행/CU)')
    brand_text = page.inner_text('#brand-list')
    check('CU' in brand_text and '16곳' in brand_text and '212곳' in brand_text and '184곳' in brand_text, '브랜드별 쉼터 수 표시')

    page.evaluate('SCSApp.map._zoom = 16; SCSApp.refreshRoads()')
    n_roads = page.evaluate('SCSApp.layers.roads.layers.length')
    check(0 < n_roads < 6000, '확대 시 화면 안 도로 그리기 (%d개)' % n_roads)
    check(not page.is_visible('#zoom-hint'), '확대하면 안내 숨김')

    # 클릭 -> 도로 선택 (파이썬이 계산한 기대값과 비교)
    ok_clicks = 0
    for c in EXPECTED['nearestRoad']:
        page.evaluate("""([x, y]) => { const ll = SCSGeo.toLonLat(x, y); SCSApp.map._zoom = 16;
                          SCSApp.map.fire('click', {latlng: {lat: ll[1], lng: ll[0]}}); }""", [c['x'], c['y']])
        if page.evaluate('SCSApp.state.road && SCSApp.state.road.id') == c['roadId']:
            ok_clicks += 1
    check(ok_clicks == len(EXPECTED['nearestRoad']), '지도 클릭으로 올바른 도로 선택 %d/%d' % (ok_clicks, len(EXPECTED['nearestRoad'])))

    page.evaluate('SCSApp.map._zoom = 12')
    before = page.evaluate('SCSApp.state.road.id')
    page.evaluate("SCSApp.map.fire('click', {latlng: {lat: 37.5665, lng: 126.978}})")
    check('확대' in page.inner_text('#status') and page.evaluate('SCSApp.state.road.id') == before, '확대 부족 시 안내하고 선택은 유지')
    page.evaluate('SCSApp.map._zoom = 16')
    page.evaluate("SCSApp.map.fire('click', {latlng: {lat: 37.30, lng: 126.30}})")
    check('도로가 없습니다' in page.inner_text('#status'), '도로 없는 곳 클릭 시 안내')

    # 도로 0(명륜10길) + 브랜드 조건
    page.evaluate('SCSApp.selectRoad(SCSApp.state.roads[0])')
    check('명륜10길' in page.inner_text('#road-info') and '$id = 0' in page.inner_text('#road-info'), '도로 정보에 이름/QGIS $id 표시')
    check(page.evaluate('SCSApp.layers.result.layers.length') == 1 + 5 + 5, '결과 레이어: 도로 1 + 연결선 5 + 마커 5')

    def verify(brands, label):
        exp = case(0, brands)
        rows = table_rows(page)
        check([r[0] for r in rows] == [x['name'] for x in exp['results']], '%s: 쉼터 이름/순서 일치 %s' % (label, [r[0] for r in rows]))
        check([r[2] for r in rows] == [fmt1(x['dist']) for x in exp['results']], '%s: 거리 표시 일치 %s' % (label, [r[2] for r in rows]))
        check([r[1] for r in rows] == [x['brand'] for x in exp['results']], '%s: 브랜드 표시 일치' % label)

    verify(None, '전체 브랜드')
    page.click('.only[data-brand="CU"]')
    check(page.evaluate('Array.from(SCSApp.state.brands)') == ['CU'], "'CU만' 버튼 -> CU만 선택")
    verify(['CU'], 'CU만')
    check('CU' in page.inner_text('#status') and '16곳' in page.inner_text('#status'), 'CU 선택 시 상태 안내(대상 16곳)')
    check(page.evaluate('SCSApp.layers.shelters.layers.filter(m => m.options.fillOpacity < 0.5).length') == 412 - 16, '선택 안 된 브랜드 쉼터는 흐리게 표시')
    check('brands=CU' in page.evaluate('location.hash') and 'road=0' in page.evaluate('location.hash'), 'URL 해시에 도로/브랜드 기록')

    page.check('#brand-list input[value="KT"]')
    verify(['CU', 'KT'], 'CU+KT')
    page.check('#brand-list input[value="신한은행"]')
    verify(None, '체크박스로 전체 복원')
    page.click('.only[data-brand="KT"]')
    verify(['KT'], 'KT만')
    page.click('.only[data-brand="신한은행"]')
    verify(['신한은행'], '신한은행만')

    page.select_option('#k-select', '3')
    check(len(table_rows(page)) == 3, '쉼터 개수 3곳으로 변경')
    page.select_option('#k-select', '10')
    check(len(table_rows(page)) == 10, '쉼터 개수 10곳으로 변경')
    page.select_option('#k-select', '5')

    # 쉼터가 모자란 경우: CU 16곳 중 상위 10 요청은 정상, K 부족 케이스는 합성 확인
    page.click('.only[data-brand="CU"]')
    page.select_option('#k-select', '10')
    check(len(table_rows(page)) == 10, 'CU 10곳 요청 -> 10곳')
    page.select_option('#k-select', '5')

    for b in ('CU', '신한은행', 'KT'):
        page.uncheck('#brand-list input[value="%s"]' % b) if page.is_checked('#brand-list input[value="%s"]' % b) else None
    check('하나 이상' in page.inner_text('#status'), '브랜드를 모두 해제하면 안내')
    page.check('#brand-list input[value="KT"]')
    page.check('#brand-list input[value="CU"]')
    page.check('#brand-list input[value="신한은행"]')

    with page.expect_download() as dl:
        page.click('#csv-nearest')
    lines = open(dl.value.path(), encoding='utf-8').read().strip().splitlines()
    check(lines[0].startswith('\ufeff순위,쉼터명,브랜드') and len(lines) == 6, 'CSV(가까운 쉼터) 헤더+5행')

    page.click('#clear-road')
    check(page.evaluate('SCSApp.state.road') is None and not page.is_visible('#result-table'), '선택 해제')
    check(len(errors) == 0, '콘솔/페이지 오류 없음 %s' % errors)
    page.close()

    # ---------------- URL 해시로 상태 복원 ----------------
    print('[UI-3] URL 해시 복원')
    other = next(c for c in EXPECTED['nearest'] if c['brands'] == ['KT'] and c['roadId'] != 0)
    page, errors = open_app(browser, port, '#tab=nearest&road=%d&brands=KT' % other['roadId'])
    rows = table_rows(page)
    check(page.is_visible('#tab-nearest'), '해시로 분석 2 탭 열림')
    check([r[0] for r in rows] == [x['name'] for x in other['results']], '해시로 도로 %d + KT 복원 -> 기대값 일치' % other['roadId'])
    check(page.evaluate('SCSApp.state.k') == 5, '기본 K=5')
    check(len(errors) == 0, '콘솔/페이지 오류 없음 %s' % errors)
    page.close()

    page, errors = open_app(browser, port, '#tab=count&method=equal&classes=4&color=green')
    check(page.input_value('#class-method') == 'equal' and page.input_value('#class-count') == '4' and page.input_value('#class-color') == 'green',
          '해시로 분류 옵션 복원')
    check(len(errors) == 0, '콘솔/페이지 오류 없음 %s' % errors)
    page.close()


if __name__ == '__main__':
    main()
