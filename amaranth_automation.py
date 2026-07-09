"""
더존 아마란스 구매발주서 브라우저 자동화

Playwright를 사용하여 아마란스 웹 화면을 자동 조작합니다.
실제 화면 구조에 맞춰 셀렉터를 수정해야 합니다.
"""

from playwright.sync_api import sync_playwright, Page, Browser

from config import AMARANTH_URL, AMARANTH_USER, AMARANTH_PASS
from models import PurchaseOrder


class AmaranthAutomation:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        print("브라우저 시작")

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        print("브라우저 종료")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("브라우저가 시작되지 않았습니다. start()를 먼저 호출하세요.")
        return self._page

    def login(self):
        """아마란스 로그인"""
        self.page.goto(AMARANTH_URL)
        self.page.wait_for_load_state("networkidle")

        # ============================================================
        # TODO: 실제 로그인 화면의 셀렉터에 맞게 수정
        # 아래는 예시이며, 실제 아마란스 로그인 페이지를 확인 후 수정 필요
        # ============================================================
        self.page.fill('input[name="userId"]', AMARANTH_USER)
        self.page.fill('input[name="password"]', AMARANTH_PASS)
        self.page.click('button[type="submit"]')
        self.page.wait_for_load_state("networkidle")

        print(f"로그인 완료: {AMARANTH_USER}")

    def navigate_to_purchase_order(self):
        """구매발주서 메뉴로 이동"""
        # ============================================================
        # TODO: 실제 메뉴 경로에 맞게 수정
        # 예: 구매관리 > 구매발주 > 구매발주서
        # ============================================================
        # self.page.click('text=구매관리')
        # self.page.click('text=구매발주')
        # self.page.click('text=구매발주서')
        # self.page.wait_for_load_state("networkidle")
        print("구매발주서 메뉴 이동 (셀렉터 설정 필요)")

    def fill_purchase_order(self, order: PurchaseOrder):
        """발주서 양식에 데이터 입력"""
        # ============================================================
        # TODO: 실제 발주서 양식의 셀렉터에 맞게 수정
        # 아래는 일반적인 ERP 발주서 양식 구조를 기반으로 한 예시입니다.
        # 실제 화면을 캡처하여 셀렉터를 확인해주세요.
        # ============================================================

        # 신규 버튼 클릭
        # self.page.click('button:has-text("신규")')

        # 헤더 정보 입력
        # self.page.fill('#supplier', order.supplier)
        # self.page.fill('#deliveryDate', order.delivery_date.strftime("%Y-%m-%d"))
        # self.page.fill('#projectCode', order.project_code)
        # self.page.fill('#accountCode', order.account_code)

        # 품목 행 입력
        for i, item in enumerate(order.items):
            self._fill_item_row(i, item)

        print(f"발주서 입력 완료: {order.supplier} ({len(order.items)}건)")

    def _fill_item_row(self, row_index: int, item):
        """품목 행 하나를 입력"""
        # ============================================================
        # TODO: 그리드/테이블의 행 입력 셀렉터에 맞게 수정
        # ERP 그리드는 보통 셀 클릭 → 입력 방식이므로
        # 실제 그리드 구조를 확인해야 합니다.
        # ============================================================

        # 행 추가 (첫 행 이후)
        # if row_index > 0:
        #     self.page.click('button:has-text("행추가")')

        # 셀 입력 예시
        # self.page.fill(f'#grid_row{row_index}_itemName', item.item_name)
        # self.page.fill(f'#grid_row{row_index}_spec', item.specification)
        # self.page.fill(f'#grid_row{row_index}_qty', str(item.quantity))
        # self.page.fill(f'#grid_row{row_index}_unit', item.unit)
        # self.page.fill(f'#grid_row{row_index}_unitPrice', str(item.unit_price))
        pass

    def submit_order(self):
        """발주서 상신"""
        # ============================================================
        # TODO: 상신 버튼 셀렉터 확인 후 수정
        # ============================================================
        # self.page.click('button:has-text("상신")')
        # self.page.wait_for_load_state("networkidle")
        print("발주서 상신 (셀렉터 설정 필요)")

    def capture_screenshot(self, name: str = "screenshot"):
        """현재 화면 캡처 (디버깅/셀렉터 확인용)"""
        path = f"screenshots/{name}.png"
        self.page.screenshot(path=path, full_page=True)
        print(f"스크린샷 저장: {path}")

    def process_order(self, order: PurchaseOrder):
        """발주서 1건 전체 처리 (이동 → 입력 → 상신)"""
        self.navigate_to_purchase_order()
        self.fill_purchase_order(order)
        self.submit_order()
