"""아마란스 발주현황에서 품번→거래처 매핑 데이터 수집"""

import json
from datetime import date

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
    print(f"로그인 완료")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # 1) 응답 캡처 + 요청 날짜 변경 설정 (네비게이션 전에!)
        captured = []
        today = date.today().strftime("%Y%m%d")

        def intercept(route, request):
            if request.method == "POST" and "poc0030" in request.url:
                body = json.loads(request.post_data)
                body["poDtFr"] = "20250101"
                body["poDtTo"] = today
                print(f"  요청 가로채기: poDtFr → 20230101")
                route.continue_(post_data=json.dumps(body))
            else:
                route.continue_()

        def on_response(response):
            if "poc0030" in response.url and response.status == 200:
                try:
                    data = response.json()
                    if data.get("resultCode") == 0:
                        captured.append(data.get("resultData", []))
                        print(f"  응답 캡처 성공: {len(captured[-1])}건")
                    else:
                        print(f"  API 오류: {data.get('resultMsg')}")
                except Exception as e:
                    print(f"  응답 파싱 실패: {e}")

        page.route("**/purchase/poc0030/**", intercept)
        page.on("response", on_response)

        # 2) 로그인
        login(page)

        # 3) 발주현황 네비게이션 (3회 시도)
        for attempt in range(3):
            print(f"\n네비게이션 시도 #{attempt + 1}")

            page.locator('text=구매/자재관리').first.click()
            page.wait_for_timeout(3000)
            page.mouse.click(800, 400)
            page.wait_for_timeout(1000)

            for m in page.locator('text=발주관리').all():
                if not m.evaluate('el => !!el.closest("#sideWrap")') and m.is_visible():
                    m.click(force=True)
                    break
            page.wait_for_timeout(1500)

            found = False
            for h in page.locator('text=발주현황').all():
                if not h.evaluate('el => !!el.closest("#sideWrap")') and h.is_visible():
                    h.click(force=True)
                    found = True
                    break

            if found:
                # 발주현황 페이지 로드 → API 자동 호출 → route 가로채기 → 응답 캡처
                for i in range(24):
                    page.wait_for_timeout(5000)
                    if captured:
                        break
                    print(f"  데이터 대기 중... ({(i+1)*5}초)")

            if captured:
                break
            print("  실패, 재시도...")

        if not captured:
            print("\n데이터 수집 실패!")
            browser.close()
            return

        # 4) 가장 큰 결과 사용
        records = max(captured, key=len)
        dates = sorted(set(r.get("poDt", "") for r in records))
        print(f"\n전체 데이터: {len(records)}건")
        print(f"날짜 범위: {dates[0]} ~ {dates[-1]}")

        # 5) 매핑 생성
        vendor_map = {}
        for r in records:
            ic = (r.get("itemCd") or "").strip()
            tn = (r.get("trNm") or "").strip()
            pd = r.get("poDt") or ""
            if ic and tn:
                if ic not in vendor_map:
                    vendor_map[ic] = []
                vendor_map[ic].append({"v": tn, "d": pd})

        final, dups = {}, {}
        for ic, entries in vendor_map.items():
            uv = list(set(e["v"] for e in entries))
            latest = sorted(entries, key=lambda x: x["d"], reverse=True)[0]
            final[ic] = latest["v"]
            if len(uv) > 1:
                dups[ic] = uv

        # 6) 저장
        with open("order_history_raw.json", "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        with open("vendor_map.json", "w", encoding="utf-8") as f:
            json.dump({"mapping": final, "duplicates": dups}, f, ensure_ascii=False, indent=2)

        print(f"\n매핑: {len(final)}개 품번, 중복: {len(dups)}개")
        if dups:
            print("거래처 중복 품번 (확인 필요):")
            for ic, vendors in dups.items():
                print(f"  {ic}: {vendors}")

        print(f"\nB0129: {final.get('B0129', '매핑 없음')}")
        print(f"C0047: {final.get('C0047', '매핑 없음')}")

        browser.close()
        print("\n완료!")


if __name__ == "__main__":
    main()
