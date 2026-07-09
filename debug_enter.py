"""Enter 시퀀스 디버그 — 각 Enter 후 어떤 셀이 활성화되는지 확인"""

from playwright.sync_api import sync_playwright
from amaranth_register import login, navigate_to_order_register


def debug_enter_sequence():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        login(page)
        navigate_to_order_register(page)
        print("=== 발주등록 진입 완료 ===\n")

        initial = page.evaluate("""() => {
            const grid = Grids.getActiveGrid();
            window._hGrid = grid;
            const dp = grid.getDataSource();
            const rowsBefore = dp.getRowCount();
            grid.beginAppendRow();
            const rowsAfter = dp.getRowCount();
            const cur = grid.getCurrent();
            return {
                rowsBefore,
                rowsAfter,
                dataRow: cur.dataRow,
                itemIndex: cur.itemIndex,
                column: cur.column,
                fieldIndex: cur.fieldIndex
            };
        }""")
        print(f"[beginAppendRow] {initial}")
        print()

        for i in range(10):
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            state = page.evaluate("""() => {
                try {
                    const grid = Grids.getActiveGrid();
                    const cur = grid.getCurrent();
                    const dp = grid.getDataSource();
                    return {
                        gridContainer: grid.container ? grid.container.id : 'no-id',
                        dataRow: cur.dataRow,
                        itemIndex: cur.itemIndex,
                        column: cur.column,
                        fieldIndex: cur.fieldIndex,
                        rowCount: dp.getRowCount()
                    };
                } catch(e) {
                    return {error: String(e)};
                }
            }""")
            print(f"[Enter {i+1:2d}] {state}")

        print("\n=== 브라우저 닫으면 종료 ===")
        page.wait_for_event("close", timeout=120000)
        browser.close()


if __name__ == "__main__":
    debug_enter_sequence()
