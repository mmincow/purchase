"""아마란스 클릭 좌표 모니터링 — 사용자가 직접 클릭하면 좌표를 파일에 기록"""

import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from config import AMARANTH_URL, AMARANTH_USER, AMARANTH_PASS

LOG_FILE = "C:/Users/somin/OneDrive/Desktop/자동화/purchase/click_coords.txt"

def login(page):
    page.goto(AMARANTH_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    page.locator("#reqLoginId").fill(AMARANTH_USER)
    next_btn = page.locator('button:has-text("다음"), a:has-text("다음")')
    if next_btn.count() > 0 and next_btn.first.is_visible():
        next_btn.first.click()
        page.wait_for_timeout(1000)
    pass_input = page.locator("#reqLoginPw")
    try:
        pass_input.wait_for(state="visible", timeout=5000)
        pass_input.fill(AMARANTH_PASS)
    except Exception:
        pass
    login_btn = page.locator('button:has-text("로그인"), a:has-text("로그인")')
    for i in range(login_btn.count()):
        if login_btn.nth(i).is_visible():
            login_btn.nth(i).click()
            break
    page.wait_for_timeout(5000)

def inject_click_monitor(page):
    """페이지에 클릭 좌표 모니터 오버레이 주입"""
    page.evaluate("""() => {
        // 오버레이 라벨 생성
        const label = document.createElement('div');
        label.id = '__click_monitor__';
        label.style.cssText = `
            position: fixed; top: 10px; right: 10px; z-index: 999999;
            background: rgba(255,0,0,0.85); color: white;
            padding: 10px 16px; border-radius: 8px;
            font-size: 18px; font-weight: bold;
            font-family: monospace; pointer-events: none;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        `;
        label.textContent = '클릭 모니터링 중...';
        document.body.appendChild(label);

        // 클릭 이벤트 리스너
        document.addEventListener('click', function(e) {
            const x = e.clientX;
            const y = e.clientY;
            label.textContent = `클릭: x=${x}, y=${y}`;
            // window 변수에도 저장
            window.__lastClick__ = {x, y, time: new Date().toISOString()};
        }, true);

        console.log('[모니터] 클릭 감지 준비됨');
    }""")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"],
        slow_mo=0,
    )
    context = browser.new_context(no_viewport=True)
    page = context.new_page()

    print("아마란스 로그인 중...")
    login(page)

    # 팝업 닫기
    for label in ["취소", "닫기", "Close"]:
        try:
            btn = page.locator(f'button:has-text("{label}")')
            if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                btn.first.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

    print("발주등록 페이지로 이동 중...")
    # 발주등록 탭이 있으면 직접 클릭
    for h in page.locator('text=발주등록').all():
        try:
            box = h.bounding_box()
            if box and box['y'] < 50 and h.is_visible():
                h.click(force=True)
                break
        except Exception:
            pass
    page.wait_for_timeout(3000)

    # 클릭 모니터 주입
    inject_click_monitor(page)

    print("=" * 50)
    print("준비 완료! 아마란스 창에서 체크박스를 클릭하세요.")
    print("클릭할 때마다 좌표가 기록됩니다.")
    print("Ctrl+C로 종료하면 결과가 저장됩니다.")
    print("=" * 50)

    clicks = []
    try:
        while True:
            page.wait_for_timeout(500)
            result = page.evaluate("() => window.__lastClick__ || null")
            if result:
                coord_str = f"x={result['x']}, y={result['y']}"
                if not clicks or clicks[-1] != coord_str:
                    clicks.append(coord_str)
                    print(f"  [클릭 감지] {coord_str}  ({result['time']})")
                    # 파일에 저장
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now().strftime('%H:%M:%S')} | {coord_str}\n")
                    # 초기화
                    page.evaluate("() => { window.__lastClick__ = null; }")
    except KeyboardInterrupt:
        print("\n종료됨.")

    if clicks:
        print("\n=== 기록된 클릭 좌표 ===")
        for c in clicks:
            print(f"  {c}")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n=== 세션 종료 ===\n")

    browser.close()
