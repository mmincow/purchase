"""
구매발주 자동화 메인 스크립트

사용법:
  1. 템플릿 생성:   python main.py --template
  2. 스크린샷 촬영:  python main.py --screenshot
  3. 발주서 상신:    python main.py --run input/발주요청.xlsx
"""

import argparse
import sys
from pathlib import Path

from amaranth_automation import AmaranthAutomation
from input_handler import read_from_excel, create_template


def run_template():
    create_template()


def run_screenshot():
    """아마란스 로그인 후 스크린샷 촬영 (셀렉터 확인용)"""
    Path("screenshots").mkdir(exist_ok=True)
    bot = AmaranthAutomation(headless=False)
    bot.start()
    try:
        bot.login()
        bot.capture_screenshot("after_login")
        bot.navigate_to_purchase_order()
        bot.capture_screenshot("purchase_order_page")
        print("스크린샷을 확인하여 셀렉터를 설정해주세요.")
        input("Enter를 누르면 브라우저를 닫습니다...")
    finally:
        bot.stop()


def run_orders(excel_path: str):
    """엑셀 파일에서 발주 데이터를 읽어 자동 상신"""
    if not Path(excel_path).exists():
        print(f"파일을 찾을 수 없습니다: {excel_path}")
        sys.exit(1)

    orders = read_from_excel(excel_path)
    if not orders:
        print("처리할 발주 데이터가 없습니다.")
        sys.exit(1)

    print(f"총 {len(orders)}건의 발주서를 처리합니다.")

    bot = AmaranthAutomation(headless=False)
    bot.start()
    try:
        bot.login()
        for i, order in enumerate(orders, 1):
            print(f"\n[{i}/{len(orders)}] {order.supplier} - {len(order.items)}개 품목")
            bot.process_order(order)
            print(f"  → 완료")
    finally:
        bot.stop()

    print(f"\n전체 {len(orders)}건 처리 완료")


def main():
    parser = argparse.ArgumentParser(description="구매발주 자동화")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template", action="store_true", help="입력용 엑셀 템플릿 생성")
    group.add_argument("--screenshot", action="store_true", help="아마란스 로그인 후 스크린샷 촬영")
    group.add_argument("--run", metavar="EXCEL", help="엑셀 파일로 발주서 자동 상신")

    args = parser.parse_args()

    if args.template:
        run_template()
    elif args.screenshot:
        run_screenshot()
    elif args.run:
        run_orders(args.run)


if __name__ == "__main__":
    main()
