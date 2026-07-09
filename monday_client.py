"""
먼데이닷컴 API 클라이언트 (확장용 구조)

나중에 먼데이닷컴 연동 시 이 모듈을 구현합니다.
- 보드에서 발주 요청 항목 조회
- 상태 업데이트 (발주완료 등)
- 웹훅 수신
"""

import requests

from config import MONDAY_API_KEY, MONDAY_BOARD_ID

MONDAY_API_URL = "https://api.monday.com/v2"


def _query(query: str, variables: dict | None = None) -> dict:
    headers = {
        "Authorization": MONDAY_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = requests.post(MONDAY_API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_pending_orders() -> list[dict]:
    """상태가 '발주요청'인 항목들을 조회 (구현 예정)"""
    # TODO: 실제 보드 컬럼 ID에 맞춰 쿼리 작성
    query = """
    query ($boardId: [ID!]) {
        boards(ids: $boardId) {
            items_page(limit: 50) {
                items {
                    id
                    name
                    column_values {
                        id
                        text
                        value
                    }
                }
            }
        }
    }
    """
    return []


def update_order_status(item_id: str, status: str) -> None:
    """발주 처리 후 먼데이닷컴 상태 업데이트 (구현 예정)"""
    # TODO: 상태 컬럼 ID 확인 후 구현
    pass
