"""
먼데이닷컴 보드 구조 조회 스크립트

사용법: python inspect_board.py
.env에 MONDAY_API_KEY를 입력한 후 실행하세요.
"""

import json
import sys

import requests

from config import MONDAY_API_KEY

MONDAY_API_URL = "https://api.monday.com/v2"
BOARD_ID = "5025883713"


def query(q: str) -> dict:
    resp = requests.post(
        MONDAY_API_URL,
        json={"query": q},
        headers={
            "Authorization": MONDAY_API_KEY,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print("API 오류:", json.dumps(data["errors"], ensure_ascii=False, indent=2))
        sys.exit(1)
    return data


def inspect_board():
    print("=" * 60)
    print("보드 구조 조회")
    print("=" * 60)

    result = query(f"""
    {{
        boards(ids: {BOARD_ID}) {{
            name
            description
            columns {{
                id
                title
                type
                settings_str
            }}
            groups {{
                id
                title
            }}
        }}
    }}
    """)

    board = result["data"]["boards"][0]
    print(f"\n보드명: {board['name']}")
    print(f"설명: {board.get('description', '없음')}")

    print(f"\n--- 컬럼 ({len(board['columns'])}개) ---")
    for col in board["columns"]:
        print(f"  [{col['id']}] {col['title']} (타입: {col['type']})")

    print(f"\n--- 그룹 ({len(board['groups'])}개) ---")
    for grp in board["groups"]:
        print(f"  [{grp['id']}] {grp['title']}")

    return board


def inspect_items(limit: int = 5):
    print("\n" + "=" * 60)
    print(f"항목 샘플 ({limit}건)")
    print("=" * 60)

    result = query(f"""
    {{
        boards(ids: {BOARD_ID}) {{
            items_page(limit: {limit}) {{
                items {{
                    id
                    name
                    group {{
                        title
                    }}
                    column_values {{
                        id
                        text
                        type
                        column {{
                            title
                        }}
                    }}
                }}
            }}
        }}
    }}
    """)

    items = result["data"]["boards"][0]["items_page"]["items"]
    for item in items:
        print(f"\n[{item['id']}] {item['name']} (그룹: {item['group']['title']})")
        for cv in item["column_values"]:
            if cv["text"]:
                print(f"  {cv['column']['title']}: {cv['text']}")


if __name__ == "__main__":
    if not MONDAY_API_KEY:
        print("오류: .env 파일에 MONDAY_API_KEY를 입력해주세요.")
        print()
        print("발급 방법:")
        print("  1. monday.com 로그인")
        print("  2. 프로필 아바타 클릭 → Developers")
        print("  3. My Access Tokens → Show 클릭 후 복사")
        sys.exit(1)

    board = inspect_board()
    inspect_items()

    print("\n\n전체 데이터를 JSON으로 저장합니다...")
    with open("board_structure.json", "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=2)
    print("저장 완료: board_structure.json")
