"""아마란스 발주등록 자동화 — 키보드 입력 방식"""

import json
from datetime import datetime

from playwright.sync_api import sync_playwright
from config import AMARANTH_URL, AMARANTH_USER, AMARANTH_PASS


def login(page):
    page.goto(AMARANTH_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    page.locator("#reqLoginId").click()
    page.locator("#reqLoginId").fill(AMARANTH_USER)
    next_btn = page.locator('button:has-text("다음"), a:has-text("다음")')
    if next_btn.count() > 0 and next_btn.first.is_visible():
        next_btn.first.click()
        page.wait_for_timeout(1000)
    pass_input = page.locator("#reqLoginPw")
    try:
        pass_input.wait_for(state="visible", timeout=5000)
        pass_input.click()
        pass_input.fill(AMARANTH_PASS)
    except Exception:
        page.evaluate('document.querySelector("#reqLoginPw").style.display = "block"')
        pass_input.fill(AMARANTH_PASS, force=True)
    login_btn = page.locator('button:has-text("로그인"), a:has-text("로그인")')
    for i in range(login_btn.count()):
        if login_btn.nth(i).is_visible():
            login_btn.nth(i).click()
            break
    page.wait_for_timeout(5000)


def dismiss_popups(page):
    """출퇴근 체크 팝업 등 로그인 후 뜨는 팝업을 취소 클릭으로 닫기."""
    for _ in range(3):
        for label in ["취소", "닫기", "Close", "Cancel"]:
            try:
                btn = page.locator(f'button:has-text("{label}"), a:has-text("{label}")')
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    print(f"  [팝업 닫기] '{label}' 클릭")
                    page.wait_for_timeout(800)
            except Exception:
                pass
        page.wait_for_timeout(500)


def navigate_to_order_register(page):
    # 출퇴근 팝업 등 닫기
    dismiss_popups(page)

    for attempt in range(6):
        menu = page.locator('text=구매/자재관리')
        if menu.count() > 0 and menu.first.is_visible():
            menu.first.click()
            break
        dismiss_popups(page)
        page.wait_for_timeout(5000)
    page.wait_for_timeout(3000)
    page.mouse.click(800, 400)
    page.wait_for_timeout(1000)
    # 발주관리 클릭 없이 발주등록 직접 클릭 (발주관리 클릭 시 발주집계로 이동됨)
    page.wait_for_timeout(2000)

    # 사이드바에서 발주등록 직접 클릭 (x < 220 = 사이드바 영역)
    clicked = False
    for h in page.locator('text=발주등록').all():
        try:
            box = h.bounding_box()
            if box and box['x'] < 220 and h.is_visible():
                h.click(force=True)
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        # 발주관리 섹션이 접혀 있는 경우 — toggle만 클릭해서 펼치기 (링크 클릭 아님)
        expanded = page.evaluate("""() => {
            for (const el of document.querySelectorAll('*')) {
                const txt = (el.textContent || '').trim();
                if (txt !== '발주관리') continue;
                const r = el.getBoundingClientRect();
                if (r.x > 220 || r.width === 0) continue;
                const parent = el.parentElement || el;
                // 토글 아이콘/버튼 찾기 (링크 아닌 것)
                for (const sel of ['[class*="toggle"]','[class*="arrow"]','[class*="expand"]','[class*="icon"]']) {
                    const btn = parent.querySelector(sel);
                    if (btn) { btn.click(); return true; }
                }
                // 부모가 <a> 태그가 아니면 클릭해서 펼치기
                if (parent.tagName !== 'A') { parent.click(); return true; }
                return false;
            }
            return false;
        }""")
        page.wait_for_timeout(1500)
        for h in page.locator('text=발주등록').all():
            try:
                box = h.bounding_box()
                if box and box['x'] < 220 and h.is_visible():
                    h.click(force=True)
                    break
            except Exception:
                pass

    page.wait_for_timeout(8000)


def _dbg(msg):
    with open("C:/Users/somin/OneDrive/Desktop/자동화/purchase/rpa_debug.txt", "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def fill_납품장소(page, text: str):
    """체크박스 → 기능모음 → 부가정보 → 납품장소 자동 입력 (text 없으면 체크박스까지만)"""
    _dbg(f"[fill_납품장소 시작] text={text[:40]!r}")
    try:
        # 1. scrollIntoView — 별도 evaluate 후 스크롤 완료 대기
        page.evaluate("""() => {
            const g = window._headerGrid;
            if (g && g.scrollIntoView && window._newOrderItemIdx !== undefined)
                g.scrollIntoView(window._newOrderItemIdx);
        }""")
        page.wait_for_timeout(700)

        # 2. 체크박스 좌표 계산
        # 사용자 직접 클릭으로 확인된 값: 체크박스 x = cr.x - 165
        # (cr.x가 사이드바 상태에 따라 변해도 오프셋 165는 고정)
        chk_pos = page.evaluate("""() => {
            try {
                const g = window._headerGrid;
                if (!g) return null;
                const idx = window._newOrderItemIdx;
                if (idx === undefined || idx === null) return null;
                const container = g.getContainer ? g.getContainer() : null;
                if (!container) return null;
                const cr = container.getBoundingClientRect();
                const ROW_H = 34;
                const HEADER_H = 34;
                const CHK_X = cr.x - 165;

                for (const fn of ['getTopItem', 'getTopIndex']) {
                    if (typeof g[fn] !== 'function') continue;
                    try {
                        const topIdx = g[fn]();
                        const visualRow = idx - topIdx;
                        if (visualRow >= 0 && visualRow < 20) {
                            return {x: CHK_X, y: cr.y + HEADER_H + visualRow * ROW_H + ROW_H/2, crX: cr.x, method: fn};
                        }
                    } catch(e) {}
                }
                return null;
            } catch(e) { return null; }
        }""")
        _dbg(f"  [체크박스 좌표] {chk_pos}")
        if not chk_pos:
            _dbg("  [체크박스] 위치 못 찾음 — 종료")
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.mouse.click(chk_pos['x'], chk_pos['y'])
        _dbg(f"  [체크박스 클릭] x={chk_pos['x']:.1f}, y={chk_pos['y']:.1f}")
        page.wait_for_timeout(800)

        # 납품장소 값 없으면 체크박스만 클릭하고 종료
        if not text:
            _dbg("  [납품장소 없음] 체크박스만 클릭하고 종료")
            return

        # 2. 기능모음 버튼 좌표 찾아서 마우스 클릭
        btn_box = page.evaluate("""() => {
            const els = [...document.querySelectorAll('*')].filter(el => {
                const txt = (el.innerText || '').trim();
                const r = el.getBoundingClientRect();
                return txt.includes('기능모음') && r.width > 0 && r.height > 0 && el.childElementCount <= 5;
            });
            if (!els.length) return null;
            els.sort((a, b) => a.childElementCount - b.childElementCount);
            const r = els[0].getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
        }""")
        if not btn_box:
            _dbg("  [기능모음] 버튼 못 찾음")
            return
        page.mouse.click(btn_box['x'], btn_box['y'])
        _dbg(f"  [기능모음] 클릭 at {btn_box}")
        page.wait_for_timeout(800)

        # 3. 부가정보 메뉴 좌표 찾아서 클릭
        sub_box = page.evaluate("""() => {
            const els = [...document.querySelectorAll('*')].filter(el => {
                const txt = (el.innerText || '').trim();
                const r = el.getBoundingClientRect();
                return txt === '부가정보' && r.width > 0 && r.height > 0;
            });
            if (!els.length) return null;
            const r = els[0].getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
        }""")
        if not sub_box:
            _dbg("  [부가정보] 메뉴 못 찾음")
            return
        page.mouse.click(sub_box['x'], sub_box['y'])
        _dbg(f"  [부가정보] 클릭 at {sub_box}")
        page.wait_for_timeout(1000)

        # 4. 납품장소 입력창 탐색
        for sel in [
            'input[id*="dlvPlc"]', 'textarea[id*="dlvPlc"]',
            'input[name*="dlvPlc"]', 'textarea[name*="dlvPlc"]',
            'label:has-text("납품장소") + input',
            'label:has-text("납품장소") + textarea',
        ]:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click()
                loc.first.fill(text)
                _dbg(f"  [납품장소 입력] {text[:40]}")
                break
        else:
            _dbg("  [납품장소] 입력창 못 찾음")
            page.screenshot(path="debug_bugage.png")
            page.keyboard.press("Escape")
            return

        # 5. 확인/저장
        ok = page.locator('button:has-text("확인"), button:has-text("저장")')
        if ok.count() > 0:
            ok.first.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(500)
    except Exception as e:
        _dbg(f"  [납품장소 오류] {e}")


def register_order(page, order):
    """
    발주 1건 등록

    order = {
        "품번": "B0129",
        "요청수량": 10000,
        "입고요청일": "2026-07-01",
        "거래처코드": "203",
        "거래처명": "주식회사어기여차크리에이티브",
        "비고": "",
    }
    """
    now = datetime.now().strftime("%Y%m%d")
    due_dt = order["입고요청일"].replace("-", "")
    item_cd = order["품번"]
    qty = str(int(order["요청수량"]))
    tr_cd = order["거래처코드"]
    tr_nm = order["거래처명"]

    # === 1단계: Tab으로 그리드 포커스 → beginAppendRow → 거래처/담당자 setValue ===
    # window scan 불가 → Tab 키로 그리드 포커스 후 getActiveGrid() 사용
    page.keyboard.press("Tab")
    page.wait_for_timeout(600)

    for attempt in range(3):
        result = page.evaluate(f"""() => {{
            const grid = Grids.getActiveGrid();
            if (!grid) return 'no_grid';
            window._headerGrid = grid;
            const dp = grid.getDataSource();

            // 기존 행에서 드롭다운 실제 코드값 읽기
            let poFgCode = '0', vatFgCode = null, umvatCode = null;
            const rowCount = dp.rowCount ? dp.rowCount() : 0;
            for (let r = 0; r < rowCount; r++) {{
                const pf = dp.getValue(r, 'poFg');
                const vf = dp.getValue(r, 'vatFg');
                const uf = dp.getValue(r, 'umvatFg');
                if (pf !== null && pf !== undefined && pf !== '') {{ poFgCode = pf; }}
                if (vf !== null && vf !== undefined && vf !== '') {{ vatFgCode = vf; }}
                if (uf !== null && uf !== undefined && uf !== '') {{ umvatCode = uf; }}
                if (vatFgCode && umvatCode) break;
            }}

            grid.beginAppendRow();
            const cur = grid.getCurrent();
            const idx = cur.dataRow !== undefined ? cur.dataRow : cur.itemIndex;
            window._newOrderItemIdx = cur.itemIndex !== undefined ? cur.itemIndex : idx;

            dp.setValue(idx, 'trCd',    '{tr_cd}');
            dp.setValue(idx, 'attrNm',  '{tr_nm}');
            dp.setValue(idx, 'plnCd',   '105');
            dp.setValue(idx, 'plnNm',   '남소민');
            dp.setValue(idx, 'poFg',    poFgCode);
            dp.setValue(idx, 'exchCd',  'KRW');
            dp.setValue(idx, 'exchRt',  1);
            if (vatFgCode !== null)  dp.setValue(idx, 'vatFg',   vatFgCode);
            if (umvatCode !== null)  dp.setValue(idx, 'umvatFg', umvatCode);

            // 기존 행 전체 필드 확인 (vatFg/umvatFg 실제 필드명 찾기)
            let rowObj = '';
            try {{
                const ro = dp.getRowObject ? dp.getRowObject(0) : null;
                if (ro) {{
                    rowObj = Object.entries(ro)
                        .filter(([k,v]) => v !== null && v !== '' && v !== undefined)
                        .map(([k,v]) => k + '=' + v).join(',');
                }}
            }} catch(e2) {{ rowObj = 'err'; }}

            const got = {{
                poFg:   dp.getValue(idx, 'poFg'),
                vatFg:  dp.getValue(idx, 'vatFg'),
                umvat:  dp.getValue(idx, 'umvatFg'),
            }};
            return 'ok:' + idx + ':src=poFg=' + poFgCode + ',vat=' + vatFgCode + ',um=' + umvatCode
                         + ':got=' + JSON.stringify(got) + ':row0=' + rowObj.substring(0,300);
        }}""")
        if result.startswith("ok"):
            print(f"  [beginAppendRow] {result}")
            break
        page.keyboard.press("Tab")
        page.wait_for_timeout(600)

    page.wait_for_timeout(500)

    # === 2단계: 헤더 필드 순서대로 Enter로 이동 ===

    # poFg (거래구분): Enter로 확인 → poDt 이동
    page.keyboard.press("Enter"); page.wait_for_timeout(300)

    # poDt (발주일자): Enter → attrNm 이동
    page.keyboard.press("Enter"); page.wait_for_timeout(300)

    # attrNm (거래처명): Escape (자동완성 닫기) + Enter → vatFg 이동
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    page.keyboard.press("Enter"); page.wait_for_timeout(400)

    # vatFg (과세구분): Enter → umvatFg 이동
    page.keyboard.press("Enter"); page.wait_for_timeout(300)

    # umvatFg (단가구분): Enter → plnNm 이동
    page.keyboard.press("Enter"); page.wait_for_timeout(300)

    cur_col = page.evaluate("""() => {
        try {
            const g = Grids.getActiveGrid() || window._headerGrid;
            return g?.getCurrent()?.column ?? null;
        } catch(e) { return null; }
    }""")
    print(f"  [Enter 5회 후 셀] {cur_col}")

    # umvatFg 팝업 닫기 + umvatFg→plnNm
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    page.keyboard.press("Enter"); page.wait_for_timeout(400)

    # plnNm 자동완성 팝업 닫기 + plnNm→mgmNm
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    page.keyboard.press("Enter"); page.wait_for_timeout(400)

    # mgmNm → remarkDcH
    page.keyboard.press("Enter"); page.wait_for_timeout(400)

    pos_after_header = page.evaluate("""() => {
        try {
            const g = Grids.getActiveGrid() || window._headerGrid;
            return g?.getCurrent()?.column ?? 'unknown';
        } catch(e) { return 'err'; }
    }""")
    print(f"  [헤더 완료 후 셀] {pos_after_header}")

    # === 발주내역 그리드로 이동: Tab 키로 헤더→발주내역 경계 넘기 ===
    in_detail = False
    for attempt in range(6):
        page.keyboard.press("Tab"); page.wait_for_timeout(400)

        result = page.evaluate(f"""() => {{
            try {{
                const g = Grids.getActiveGrid();
                if (!g) return 'no_grid';
                if (g === window._headerGrid) return 'header';
                // 발주내역 그리드 발견
                window._detailGrid = g;
                g.beginAppendRow();
                const cur = g.getCurrent();
                const idx = cur.dataRow !== undefined ? cur.dataRow : cur.itemIndex;
                return 'detail:' + idx;
            }} catch(e) {{ return 'err:' + String(e); }}
        }}""")
        print(f"  [발주내역 탐색 {attempt+1}] {result}")
        if result.startswith("detail:"):
            in_detail = True
            break

    if not in_detail:
        print("  [경고] 발주내역 그리드 미진입 - Tab 재시도 필요")

    page.wait_for_timeout(500)

    # === 발주내역: 현재 셀 확인 후 dp.setValue + 품번 키보드 입력 ===
    detail_init = page.evaluate(f"""() => {{
        try {{
            const g = Grids.getActiveGrid() || window._detailGrid;
            if (!g) return 'no_grid';
            const dp = g.getDataSource();
            const cur = g.getCurrent();
            const dataRow = cur.dataRow !== undefined ? cur.dataRow : cur.itemIndex;
            const itemIdx = cur.itemIndex;

            // 날짜/수량 dp.setValue로 직접 설정
            dp.setValue(dataRow, 'dueDt',     '{due_dt}');
            dp.setValue(dataRow, 'shipreqDt', '{due_dt}');
            dp.setValue(dataRow, 'poQt',       {qty});

            // itemCd 셀로 커서 이동
            try {{ g.setCurrent({{itemIndex: itemIdx, column: 'itemCd'}}); }} catch(e2) {{}}

            const got = {{
                col:       cur.column,
                itemIdx:   itemIdx,
                dataRow:   dataRow,
                dueDt:     dp.getValue(dataRow, 'dueDt'),
                shipreqDt: dp.getValue(dataRow, 'shipreqDt'),
                poQt:      dp.getValue(dataRow, 'poQt'),
            }};
            return JSON.stringify(got);
        }} catch(e) {{ return 'err:' + e; }}
    }}""")
    print(f"  [발주내역 init] {detail_init}")

    page.wait_for_timeout(300)

    # 품번 키보드 입력 → Tab으로 품명 자동매핑 트리거
    page.keyboard.type(item_cd)
    page.wait_for_timeout(500)
    page.keyboard.press("Tab")
    page.wait_for_timeout(2500)  # 품명 조회 대기

    after_item = page.evaluate("""() => {
        try {
            const g = Grids.getActiveGrid() || window._detailGrid;
            return g?.getCurrent()?.column ?? 'unknown';
        } catch(e) { return 'err'; }
    }""")
    print(f"  [품번 Tab 후 셀] {after_item}")

    # === 헤더 그리드 빈 행으로 이동 → 발주번호 생성 ===
    page.wait_for_timeout(500)

    # setCurrent로 마지막 행 아래 빈 행 이동 (클릭과 동일 효과)
    move_result = page.evaluate("""() => {
        try {
            const g = window._headerGrid;
            if (!g) return 'no_grid';
            g.setFocus();
            const count = g.getItemCount ? g.getItemCount() : 0;
            g.setCurrent({itemIndex: count, column: 'poFg'});
            return 'moved_to:' + count;
        } catch(e) { return 'err:' + e; }
    }""")
    print(f"  [빈 행 이동] {move_result}")
    page.wait_for_timeout(2000)

    # setCurrent 실패 시 fallback: 캔버스 맨 아래 클릭
    if 'err' in str(move_result) or 'no_grid' in str(move_result):
        click_pos = page.evaluate("""() => {
            try {
                const canvases = [...document.querySelectorAll('canvas')];
                const c = canvases.reduce((a,b) =>
                    a.getBoundingClientRect().width > b.getBoundingClientRect().width ? a : b);
                const r = c.getBoundingClientRect();
                return {x: r.left + 100, y: r.bottom - 15};
            } catch(e) { return null; }
        }""")
        if click_pos:
            page.mouse.click(click_pos['x'], click_pos['y'])
            page.wait_for_timeout(2000)
            print(f"  [캔버스 하단 클릭] {click_pos}")

    # 발주번호 캡처 (setCurrent 후 서버가 생성)
    po_no = ""
    for _ in range(5):
        po_no = page.evaluate("""() => {
            try {
                const g = window._headerGrid;
                if (!g) return '';
                const dp = g.getDataSource();
                const rc = dp.rowCount ? dp.rowCount() : 0;
                for (let i = rc - 1; i >= 0; i--) {
                    const pn = dp.getValue(i, 'poNo');
                    if (pn) return String(pn);
                }
                return '';
            } catch(e) { return ''; }
        }""")
        if po_no:
            break
        page.wait_for_timeout(1000)

    print(f"  [발주번호] {po_no}")

    # 체크박스 클릭 → 납품장소 있으면 기능모음 → 부가정보까지
    납품장소 = order.get("납품장소", "")
    _dbg(f"  [납품장소 값] {납품장소!r}")
    fill_납품장소(page, 납품장소)

    return {"status": 200, "body": f"{item_cd} 입력 완료", "poNo": po_no}


def delete_order_rpa(po_no: str):
    """아마란스에서 발주번호로 발주 삭제"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        page = browser.new_page(no_viewport=True)

        login(page)
        navigate_to_order_register(page)

        # F10으로 조회 (Amaranth 10 조회 단축키)
        page.wait_for_timeout(1000)
        page.keyboard.press("F10")
        print("  [F10 조회 실행]")
        page.wait_for_timeout(5000)

        # 그리드 진단: _headerGrid 및 window 스캔
        diag = page.evaluate("""() => {
            try {
                // 1) _headerGrid 직접 확인
                const g = window._headerGrid;
                if (!g) {
                    // window에서 getItemCount 있는 객체 찾기
                    const cands = [];
                    for (const k of Object.keys(window)) {
                        try {
                            const v = window[k];
                            if (v && typeof v.getItemCount === 'function') {
                                cands.push(k + '(ic=' + v.getItemCount() + ')');
                            }
                        } catch(e) {}
                    }
                    return 'no_headerGrid, cands=' + cands.join(',');
                }
                const rc = g.getItemCount ? g.getItemCount() : -1;
                const dp = g.getDataSource();
                const dpType = dp ? (dp.constructor ? dp.constructor.name : '?') : 'null';
                // dp.rowCount 확인 (함수 vs 속성)
                let drc = 'N/A';
                try { drc = typeof dp.rowCount === 'function' ? dp.rowCount() : dp.rowCount; } catch(e) { drc = 'err'; }
                // dp.getValue(0, 'poNo') 직접 시도
                let v0 = 'N/A';
                try { v0 = String(dp.getValue(0, 'poNo')); } catch(e) { v0 = 'err:' + e.message; }
                // g.getDataRow(0) 시도
                let dr0 = 'N/A';
                try { dr0 = typeof g.getDataRow === 'function' ? g.getDataRow(0) : 'no_fn'; } catch(e) { dr0 = 'err:' + e.message; }
                // getDataRow 결과로 다시 getValue
                let v0dr = 'N/A';
                try { if (typeof dr0 === 'number') v0dr = String(dp.getValue(dr0, 'poNo')); } catch(e) { v0dr = 'err:' + e.message; }
                return 'ic=' + rc + ',drc=' + drc + ',dpType=' + dpType + ',v0direct=' + v0 + ',dr0=' + dr0 + ',v0viadr=' + v0dr;
            } catch(e) { return 'err:' + String(e); }
        }""")
        print(f"  [진단] {diag}")

        # 발주번호로 행 검색 — _headerGrid + getItemCount 방식
        found = page.evaluate(f"""() => {{
            try {{
                const g = window._headerGrid;
                if (!g) return 'no_headerGrid';
                const rc = g.getItemCount ? g.getItemCount() : 0;
                const dp = g.getDataSource();
                for (let i = 0; i < rc; i++) {{
                    let pn = null;
                    // A: getDataRow → dp.getValue
                    try {{
                        if (typeof g.getDataRow === 'function') {{
                            const dr = g.getDataRow(i);
                            pn = dp.getValue(dr, 'poNo');
                        }}
                    }} catch(eA) {{}}
                    // B: itemIndex 직접
                    if (!pn) try {{ pn = dp.getValue(i, 'poNo'); }} catch(eB) {{}}
                    if (pn && String(pn) === '{po_no}') {{
                        g.checkItem(i, true);
                        g.setCurrent({{itemIndex: i, column: 'poFg'}});
                        return 'found:' + i;
                    }}
                }}
                return 'not_found (ic=' + rc + ')';
            }} catch(e) {{ return 'err:' + String(e); }}
        }}""")
        print(f"  [발주 찾기] {found}")

        if not str(found).startswith("found"):
            print(f"  [오류] {po_no} 를 찾을 수 없음")
            browser.close()
            return False

        page.wait_for_timeout(500)

        # F7로 삭제 (Amaranth 10 삭제 단축키)
        page.keyboard.press("F7")
        print("  [F7 삭제 실행]")
        page.wait_for_timeout(1000)

        # 확인 팝업 처리 (Enter = 확인)
        page.keyboard.press("Enter")
        print("  [Enter 확인]")

        page.wait_for_timeout(2000)
        browser.close()
        print(f"  [삭제 완료] {po_no}")
        return True


def register_orders(orders):
    """여러 발주 건 등록"""
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        page = browser.new_page(no_viewport=True)

        login(page)
        navigate_to_order_register(page)
        print("발주등록 페이지 진입 완료")

        for i, order in enumerate(orders):
            print(f"\n[{i+1}/{len(orders)}] {order['품번']} - {order['거래처명']}")
            result = register_order(page, order)
            print(f"  결과: {result}")
            results.append({**order, "result": result})

        # 입력 완료 — 사용자 확인 대기
        print("\n=== 입력 완료 ===")
        print("브라우저에서 내용 확인 후 저장/결재상신 해주세요.")
        print("브라우저를 닫으면 종료됩니다.")
        try:
            page.wait_for_event("close", timeout=600000)
        except Exception:
            pass

        browser.close()

    return results


if __name__ == "__main__":
    test_orders = [
        {
            "품번": "B0129",
            "요청수량": 10000,
            "입고요청일": "2026-07-01",
            "거래처코드": "203",
            "거래처명": "주식회사어기여차크리에이티브",
            "비고": "",
        },
    ]

    results = register_orders(test_orders)
    with open("last_register_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
