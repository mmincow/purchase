"""더존 아마란스 로그인 테스트"""

from playwright.sync_api import sync_playwright
from config import AMARANTH_URL, AMARANTH_USER, AMARANTH_PASS


def test_login():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"접속 중: {AMARANTH_URL}")
        page.goto(AMARANTH_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # 아이디 입력
        user_input = page.locator('#reqLoginId')
        user_input.click()
        user_input.fill(AMARANTH_USER)
        print(f"아이디 입력 완료: {AMARANTH_USER}")

        page.screenshot(path="screenshot_01_id_filled.png")

        # 다음 버튼 또는 탭으로 비밀번호 필드 활성화
        next_btn = page.locator('button:has-text("다음"), .btn_next, a:has-text("다음")')
        if next_btn.count() > 0 and next_btn.first.is_visible():
            print("다음 버튼 클릭")
            next_btn.first.click()
            page.wait_for_timeout(1000)
        else:
            user_input.press("Tab")
            page.wait_for_timeout(1000)

        page.screenshot(path="screenshot_02_after_next.png")

        # 비밀번호 입력
        pass_input = page.locator('#reqLoginPw')
        try:
            pass_input.wait_for(state="visible", timeout=5000)
            pass_input.click()
            pass_input.fill(AMARANTH_PASS)
            print("비밀번호 입력 완료")
        except Exception:
            print("비밀번호 필드가 보이지 않음, force로 시도")
            page.evaluate('document.querySelector("#reqLoginPw").style.display = "block"')
            page.evaluate('document.querySelector("#reqLoginPw").style.visibility = "visible"')
            pass_input.fill(AMARANTH_PASS, force=True)

        page.screenshot(path="screenshot_03_pw_filled.png")

        # 로그인 버튼 클릭
        login_btn = page.locator('button:has-text("로그인"), .btn_login, a:has-text("로그인")')
        if login_btn.count() > 0:
            for i in range(login_btn.count()):
                btn = login_btn.nth(i)
                if btn.is_visible():
                    print(f"로그인 버튼 클릭")
                    btn.click()
                    break
        else:
            pass_input.press("Enter")

        page.wait_for_timeout(5000)

        page.screenshot(path="screenshot_04_after_login.png")
        print(f"\n로그인 후 URL: {page.url}")
        print(f"페이지 타이틀: {page.title()}")

        browser.close()
        print("\n로그인 테스트 완료!")


if __name__ == "__main__":
    test_login()
