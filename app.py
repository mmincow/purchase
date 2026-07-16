"""발주 확인 웹앱 - FastAPI (Monday.com 스타일)"""

import base64
import json
import subprocess
import threading
import time
import winsound
from datetime import date, datetime
from pathlib import Path

import openpyxl
import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from config import MONDAY_API_KEY

app = FastAPI(title="구매발주 자동화")

# ── 실시간 알람용 상태 ──────────────────────────────────────
_known_ids: set = set()
_new_orders: list = []
_poll_lock = threading.Lock()


def _win_notify(title: str, body: str):
    """Windows 토스트 알림 + 비프음 (브라우저 무관)."""
    try:
        winsound.Beep(880, 500)
    except Exception:
        pass
    # base64-encoded UTF-16LE로 전달 → 한글/특수문자 인코딩 문제 없음
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null\n"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]"
        "::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
        f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title}'))|Out-Null\n"
        f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{body}'))|Out-Null\n"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($t)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('구매발주').Show($n)\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell", "-EncodedCommand", encoded],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _background_poller():
    """60초마다 Monday.com 확인 → 새 발주 감지 → Windows 알림."""
    global _known_ids, _new_orders
    first_run = True
    while True:
        try:
            orders = get_pending_orders()
            current_ids = {o["id"] for o in orders}
            with _poll_lock:
                if not first_run:
                    new_ids = current_ids - _known_ids
                    if new_ids:
                        new = [o for o in orders if o["id"] in new_ids]
                        _new_orders = new
                        body = "\n".join(f"{o['품번']} / {o['요청수량']}개" for o in new)
                        threading.Thread(
                            target=_win_notify,
                            args=(f"새 발주 요청 {len(new)}건!", body),
                            daemon=True,
                        ).start()
                _known_ids = current_ids
                first_run = False
        except Exception as e:
            print(f"[poller] 오류: {e}")
        time.sleep(60)


threading.Thread(target=_background_poller, daemon=True).start()

MONDAY_API_URL = "https://api.monday.com/v2"
BOARD_ID = "5025883713"
BASE_DIR = Path(__file__).parent
REGISTERED_FILE = BASE_DIR / "registered_orders.json"
DISMISSED_FILE = BASE_DIR / "dismissed_orders.json"
AUDIT_FILE = BASE_DIR / "audit_log.json"

# 납품장소 매핑 (입고처 코드 → 납품장소 전체 텍스트)
_납품장소_map: dict = {}
try:
    _wb = openpyxl.load_workbook(BASE_DIR / "입고처 및 납품장소.xlsx")
    for _row in _wb.active.iter_rows(min_row=2, values_only=True):
        if _row[0] and _row[1]:
            _납품장소_map[str(_row[0]).strip()] = str(_row[1]).strip()
    print(f"납품장소 매핑 {len(_납품장소_map)}건 로드")
except Exception as _e:
    print(f"납품장소 Excel 로딩 오류: {_e}")


def load_registered_orders() -> list:
    if not REGISTERED_FILE.exists():
        return []
    with open(REGISTERED_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_registered_orders(new_orders: list):
    existing = load_registered_orders()
    existing_ids = {r["id"] for r in existing}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for o in new_orders:
        oid = str(o.get("id", ""))
        if oid and oid not in existing_ids:
            existing.append({
                "id": oid,
                "품번": o.get("품번", ""),
                "요청수량": str(o.get("요청수량", "")),
                "입고요청일": o.get("입고요청일", ""),
                "거래처": o.get("거래처", o.get("거래처명", "")),
                "담당자": o.get("담당자", ""),
                "registered_at": now,
            })
    with open(REGISTERED_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_dismissed_ids() -> set:
    if not DISMISSED_FILE.exists():
        return set()
    with open(DISMISSED_FILE, encoding="utf-8") as f:
        return {str(r["id"]) for r in json.load(f)}


def append_audit(action: str, operator: str, detail: str):
    """작업 감사 로그: 누가(담당자) 언제 무엇을 했는지 기록."""
    records = []
    if AUDIT_FILE.exists():
        with open(AUDIT_FILE, encoding="utf-8") as f:
            records = json.load(f)
    records.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "담당자": operator.strip() or "미입력",
        "작업": action,
        "내용": detail,
    })
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_audit_log(limit: int = 30) -> list:
    if not AUDIT_FILE.exists():
        return []
    with open(AUDIT_FILE, encoding="utf-8") as f:
        records = json.load(f)
    return list(reversed(records[-limit:]))


def load_vendor_map():
    """vendor_map.json에서 품번→거래처 매핑 로드"""
    path = BASE_DIR / "vendor_map.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("mapping", {}), data.get("duplicates", {})
    return {}, {}


def build_item_vendors():
    """order_history_raw.json에서 품번별 전체 거래처 목록 구축"""
    raw_path = BASE_DIR / "order_history_raw.json"
    if not raw_path.exists():
        return {}
    with open(raw_path, encoding="utf-8") as f:
        raw_data = json.load(f)
    item_vendors: dict[str, list[str]] = {}
    for r in raw_data:
        item_cd = (r.get("itemCd") or "").strip()
        tr_nm = (r.get("trNm") or "").strip()
        if item_cd and tr_nm:
            if item_cd not in item_vendors:
                item_vendors[item_cd] = []
            if tr_nm not in item_vendors[item_cd]:
                item_vendors[item_cd].append(tr_nm)
    return item_vendors


def monday_query(q: str) -> dict:
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
    return resp.json()


def get_pending_orders():
    """먼데이닷컴에서 '발주 요청' 그룹 + '요청 완료' 상태 항목 가져오기"""
    result = monday_query(f"""
    {{
        boards(ids: {BOARD_ID}) {{
            items_page(limit: 50, query_params: {{
                rules: [
                    {{column_id: "status", compare_value: [1]}}
                ]
            }}) {{
                items {{
                    id
                    name
                    group {{ id title }}
                    column_values {{
                        id
                        text
                        type
                        column {{ title }}
                    }}
                }}
            }}
        }}
    }}
    """)

    items = result["data"]["boards"][0]["items_page"]["items"]
    orders = []
    for item in items:
        if item["group"]["id"] != "topics":
            continue

        cols = {cv["id"]: cv["text"] for cv in item["column_values"] if cv["text"]}
        orders.append({
            "id": item["id"],
            "품번": item["name"],
            "품명": cols.get("text", ""),
            "현재고": cols.get("numeric5", ""),
            "요청수량": cols.get("numeric", ""),
            "예상소진월": cols.get("numeric_mm0xdtf5", ""),
            "발주요청일": cols.get("date4", ""),
            "입고요청일": cols.get("date", ""),
            "생산기지": cols.get("dropdown_mkv64zc9", ""),
            "입고처": cols.get("dropdown_mkqzwbdz", ""),
            "요청사유": cols.get("text5", ""),
            "요청자": cols.get("person", ""),
            "담당부서": cols.get("color_mm2pw122", ""),
        })

    return orders


@app.get("/api/orders")
async def api_orders_list():
    """현재 발주 대기 목록 JSON (브라우저 polling용)."""
    try:
        return JSONResponse(get_pending_orders())
    except Exception as e:
        return JSONResponse([], status_code=500)


@app.get("/api/new-orders")
async def api_new_orders():
    """새로 감지된 발주 건 반환 후 초기화."""
    global _new_orders
    with _poll_lock:
        result = list(_new_orders)
        _new_orders = []
    return JSONResponse(result)


@app.post("/api/cancel-order")
async def api_cancel_order(request: dict):
    """발주 취소: 웹앱 등록완료 목록에서 제거 + 아마란스 자동 삭제."""
    order_id = str(request.get("id", ""))
    po_no = request.get("po_no", "")
    operator = str(request.get("담당자", ""))
    append_audit("발주취소", operator, f"등록된 발주 취소 — {po_no or '발주번호 없음'}")

    # registered_orders.json에서 제거
    existing = load_registered_orders()
    updated = [r for r in existing if r["id"] != order_id]
    with open(REGISTERED_FILE, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    # 아마란스 삭제 RPA (발주번호 있을 때만)
    if po_no:
        from amaranth_register import delete_order_rpa
        threading.Thread(target=delete_order_rpa, args=(po_no,), daemon=True).start()

    return JSONResponse({"ok": True, "po_no": po_no})


@app.post("/api/dismiss-order")
async def api_dismiss_order(request: dict):
    """발주 불필요 삭제: 대기 목록에서 영구 제외 — 아마란스 등록이 진행되지 않음."""
    order_id = str(request.get("id", ""))
    operator = str(request.get("담당자", ""))
    if not order_id:
        return JSONResponse({"ok": False, "error": "id 없음"}, status_code=400)

    records = []
    if DISMISSED_FILE.exists():
        with open(DISMISSED_FILE, encoding="utf-8") as f:
            records = json.load(f)
    if order_id not in {str(r["id"]) for r in records}:
        records.append({
            "id": order_id,
            "품번": request.get("품번", ""),
            "담당자": operator,
            "dismissed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        with open(DISMISSED_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    append_audit("삭제", operator, f"발주 요청 삭제 — 품번 {request.get('품번', '?')}")
    return JSONResponse({"ok": True})


@app.post("/api/mark-registered")
async def api_mark_registered(request: dict):
    """수동으로 등록 완료 처리."""
    orders = request.get("orders", [])
    if orders:
        save_registered_orders(orders)
    return JSONResponse({"ok": True, "count": len(orders)})


@app.get("/api/test-notification")
async def api_test_notification():
    """알람 테스트용 — Windows 토스트 알림 + 비프음 즉시 발송."""
    threading.Thread(
        target=_win_notify,
        args=("새 발주 요청 테스트", "알람이 정상 작동합니다!"),
        daemon=True,
    ).start()
    return JSONResponse({"ok": True})


@app.post("/api/register")
async def api_register(request: dict):
    """확인 완료된 발주 건을 아마란스에 등록"""
    orders = request.get("orders", [])
    operator = str(request.get("담당자", ""))
    if not orders:
        return JSONResponse({"status": "error", "message": "등록할 항목이 없습니다"})

    item_list = ", ".join(o.get("품번", "?") for o in orders)
    append_audit("발주등록 요청", operator, f"{len(orders)}건 아마란스 등록 — {item_list}")

    vendor_map, _ = load_vendor_map()

    # 거래처코드 매핑 (vendor_map.json + order_history_raw.json에서 trCd 찾기)
    tr_code_map = {}
    raw_path = BASE_DIR / "order_history_raw.json"
    if raw_path.exists():
        with open(raw_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        for r in raw_data:
            item_cd = (r.get("itemCd") or "").strip()
            tr_nm = (r.get("trNm") or "").strip()
            tr_cd = (r.get("trCd") or "").strip()
            if item_cd and tr_nm and tr_cd:
                tr_code_map[(item_cd, tr_nm)] = tr_cd
                tr_code_map[tr_nm] = tr_cd

    # 발주 데이터 준비
    rpa_orders = []
    for o in orders:
        vendor_name = o.get("거래처", "")
        vendor_code = tr_code_map.get((o["품번"], vendor_name), tr_code_map.get(vendor_name, ""))
        ingochu = str(o.get("입고처", "")).strip()
        dlvplc = _납품장소_map.get(ingochu, "")
        print(f"  [납품장소 매핑] {o['품번']}: 입고처={ingochu!r} → 납품장소={dlvplc[:30]!r}")
        rpa_orders.append({
            "품번": o["품번"],
            "요청수량": int(o.get("요청수량", 0)),
            "입고요청일": o.get("입고요청일", ""),
            "거래처코드": vendor_code,
            "거래처명": vendor_name,
            "비고": o.get("비고", ""),
            "납품장소": dlvplc,
        })

    # 등록 완료 목록에 저장 (담당자 포함)
    for o in orders:
        o["담당자"] = operator
    save_registered_orders(orders)

    # 백그라운드에서 RPA 실행
    import threading
    from amaranth_register import register_orders

    def run_rpa():
        try:
            results = register_orders(rpa_orders)
            result_path = BASE_DIR / "last_register_result.json"
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            # 발주번호를 registered_orders.json에 업데이트
            registered = load_registered_orders()
            id_map = {o["품번"]: str(o["id"]) for o in orders}
            for res in results:
                po_no = (res.get("result") or {}).get("poNo", "")
                oid = id_map.get(res.get("품번", ""), "")
                if po_no and oid:
                    for r in registered:
                        if r["id"] == oid:
                            r["po_no"] = po_no
                            break
            with open(REGISTERED_FILE, "w", encoding="utf-8") as f:
                json.dump(registered, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"RPA 오류: {e}")

    thread = threading.Thread(target=run_rpa, daemon=True)
    thread.start()

    return JSONResponse({
        "status": "ok",
        "message": f"{len(rpa_orders)}건 아마란스 등록 시작",
        "orders": rpa_orders,
    })


@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        orders = get_pending_orders()
    except Exception as e:
        orders = []
        error = str(e)
    else:
        error = None

    # 등록완료 분리
    registered_data = load_registered_orders()
    registered_ids = {r["id"] for r in registered_data}
    dismissed_ids = load_dismissed_ids()
    pending_orders = [
        o for o in orders
        if str(o["id"]) not in registered_ids and str(o["id"]) not in dismissed_ids
    ]
    monday_map = {o["id"]: o for o in orders}
    reg_display = []
    for r in reversed(registered_data):
        mo = monday_map.get(r["id"], {})
        reg_display.append({**r, "품명": mo.get("품명", "-")})

    vendor_map, vendor_duplicates = load_vendor_map()
    item_vendors = build_item_vendors()
    audit_entries = load_audit_log(30)
    today = date.today().strftime("%Y년 %m월 %d일")

    # 거래처 매핑 데이터를 JSON으로 준비
    vendor_json = json.dumps(vendor_map, ensure_ascii=False)
    dup_json = json.dumps(vendor_duplicates, ensure_ascii=False)
    item_vendors_json = json.dumps(item_vendors, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>구매발주 자동화</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Noto Sans KR', 'Segoe UI', sans-serif; background: #f7f8fc; color: #3b3f5c; min-height: 100vh; }}
        .sidebar {{
            position: fixed; left: 0; top: 0; bottom: 0; width: 58px;
            background: #ffffff; border-right: 1px solid #e8eaf0;
            display: flex; flex-direction: column; align-items: center;
            padding-top: 16px; z-index: 100;
            box-shadow: 1px 0 4px rgba(0,0,0,0.04);
        }}
        .sidebar .logo {{
            width: 34px; height: 34px; background: linear-gradient(135deg, #e8663c, #f5a623);
            border-radius: 8px; margin-bottom: 24px;
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 14px; color: white;
        }}
        .sidebar .nav-item {{
            width: 36px; height: 36px; border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 8px; cursor: pointer; transition: background 0.2s;
            color: #a0a4b8;
        }}
        .sidebar .nav-item:hover {{ background: #f0f1f7; }}
        .sidebar .nav-item.active {{ background: #ddd4ff; color: #6246ea; }}
        .sidebar .nav-item svg {{ width: 18px; height: 18px; fill: currentColor; }}
        .main {{ margin-left: 58px; }}
        .top-header {{
            background: #ffffff; padding: 12px 28px;
            display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid #e8eaf0;
        }}
        .top-header .board-title {{
            font-size: 18px; font-weight: 700; color: #3b3f5c;
            display: flex; align-items: center; gap: 10px;
        }}
        .top-header .board-title .icon {{
            width: 28px; height: 28px; background: #6a9bff;
            border-radius: 6px; display: flex; align-items: center; justify-content: center;
        }}
        .top-header .board-title .icon svg {{ width: 16px; height: 16px; fill: white; }}
        .top-header .user-info {{
            display: flex; align-items: center; gap: 12px;
            font-size: 13px; color: #7a7f9a;
        }}
        .avatar {{
            width: 32px; height: 32px; border-radius: 50%;
            background: linear-gradient(135deg, #56c596, #3aab7b);
            display: flex; align-items: center; justify-content: center;
            font-size: 13px; font-weight: 600; color: white;
        }}
        .toolbar {{
            background: #ffffff; padding: 10px 28px;
            display: flex; align-items: center; gap: 12px;
            border-bottom: 1px solid #e8eaf0;
        }}
        .toolbar .tool-btn {{
            padding: 6px 14px; border-radius: 6px; border: 1px solid #e0e2ea;
            background: transparent; color: #7a7f9a; font-size: 13px;
            cursor: pointer; transition: all 0.2s; font-family: inherit;
        }}
        .toolbar .tool-btn:hover {{ background: #f0f1f7; color: #3b3f5c; }}
        .toolbar .tool-btn.primary {{ background: #6a9bff; border-color: #6a9bff; color: white; }}
        .toolbar .tool-btn.primary:hover {{ background: #5588f0; }}
        .toolbar .tool-btn.success {{ background: #56c596; border-color: #56c596; color: white; }}
        .toolbar .tool-btn.success:hover {{ background: #45b585; }}
        .toolbar .separator {{ width: 1px; height: 24px; background: #e0e2ea; }}
        .toolbar .status-count {{ font-size: 13px; color: #7a7f9a; display: flex; align-items: center; gap: 6px; }}
        .toolbar .status-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
        .dot-pending {{ background: #f5a623; }}
        .dot-confirmed {{ background: #56c596; }}
        .board-content {{ padding: 0; }}
        .group-header {{ padding: 12px 28px; display: flex; align-items: center; gap: 10px; }}
        .group-header .group-color {{ width: 6px; height: 30px; border-radius: 3px; }}
        .group-header .group-title {{ font-size: 15px; font-weight: 700; }}
        .group-header .group-count {{ font-size: 13px; color: #7a7f9a; background: #eef0f6; padding: 2px 10px; border-radius: 10px; }}
        .table-wrapper {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        thead th {{ background: #f7f8fc; color: #7a7f9a; padding: 8px 12px; text-align: left; font-weight: 500; font-size: 12px; border-bottom: 1px solid #e8eaf0; position: sticky; top: 0; white-space: nowrap; }}
        thead th:first-child {{ padding-left: 28px; }}
        tbody td {{ padding: 10px 12px; border-bottom: 1px solid #eef0f6; color: #3b3f5c; white-space: nowrap; background: #ffffff; }}
        tbody td:first-child {{ padding-left: 28px; }}
        tbody tr {{ transition: background 0.15s; }}
        tbody tr:hover td {{ background: #f0f4ff; }}
        .status-pill {{ display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: 12px; font-weight: 600; text-align: center; min-width: 80px; }}
        .pill-pending {{ background: #ffecd2; color: #c56a15; }}
        .pill-confirmed {{ background: #d4f5e2; color: #1e7a48; }}
        .pill-registering {{ background: #dce8ff; color: #3a6bd5; }}
        .pill-done {{ background: #e6d9ff; color: #6246ea; }}
        .pill-inhouse {{ background: #e6d9ff; color: #6246ea; }}
        .pill-outsource {{ background: #ffddd2; color: #c94a2a; }}
        .cell-input {{ background: #f7f8fc; border: 1px solid #e0e2ea; color: #3b3f5c; padding: 5px 10px; border-radius: 6px; font-size: 12px; width: 100%; min-width: 120px; font-family: inherit; }}
        .cell-input:focus {{ outline: none; border-color: #a8c5ff; background: #fff; box-shadow: 0 0 0 2px rgba(168,197,255,0.3); }}
        .vendor-input {{ background: #f7f8fc; border: 1px solid #e0e2ea; color: #3b3f5c; padding: 5px 10px; border-radius: 6px; font-size: 12px; font-family: inherit; min-width: 180px; width: 100%; }}
        .vendor-input:focus {{ outline: none; border-color: #a8c5ff; background: #fff; box-shadow: 0 0 0 2px rgba(168,197,255,0.3); }}
        .vendor-input.warn {{ border-color: #f5a623; background: #fff9f0; }}
        .vendor-input.mapped {{ border-color: #56c596; background: #f0faf5; }}
        .vendor-input.unmapped {{ border-color: #e85d4a; background: #fef5f4; }}
        .vendor-input:disabled {{ opacity: 0.6; cursor: not-allowed; }}
        .row-btn {{ padding: 5px 14px; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: inherit; }}
        .row-btn-confirm {{ background: #6a9bff; color: white; }}
        .row-btn-confirm:hover {{ background: #5588f0; }}
        .row-btn-delete {{ background: #ffddd2; color: #c94a2a; margin-left: 4px; }}
        .row-btn-delete:hover {{ background: #ffc9b8; }}
        .summary-bar {{ background: #ffffff; border-top: 1px solid #e8eaf0; padding: 12px 28px; display: flex; gap: 32px; position: sticky; bottom: 0; box-shadow: 0 -1px 4px rgba(0,0,0,0.04); }}
        .summary-item {{ display: flex; align-items: center; gap: 8px; }}
        .summary-item .s-label {{ font-size: 12px; color: #a0a4b8; }}
        .summary-item .s-value {{ font-size: 16px; font-weight: 700; }}
        .s-value.pending {{ color: #c56a15; }}
        .s-value.confirmed {{ color: #1e7a48; }}
        .s-value.registered {{ color: #3a6bd5; }}
        .toast {{ position: fixed; bottom: 60px; right: 24px; background: #56c596; color: #fff; padding: 14px 24px; border-radius: 8px; font-size: 14px; font-weight: 500; display: none; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        .toast.error {{ background: #e85d4a; }}
        .toast.show {{ display: block; animation: slideUp 0.3s; }}
        @keyframes slideUp {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .empty-state {{ text-align: center; padding: 80px 20px; }}
        .empty-state h2 {{ font-size: 20px; color: #3b3f5c; margin-bottom: 8px; }}
        .empty-state p {{ color: #a0a4b8; font-size: 14px; }}
        .item-code-cell {{ color: #3a6bd5; font-weight: 600; cursor: pointer; }}
        .item-code-cell:hover {{ text-decoration: underline; }}
        .vendor-tag {{ font-size: 10px; margin-left: 4px; padding: 1px 6px; border-radius: 4px; }}
        .vendor-tag.auto {{ background: #d4f5e2; color: #1e7a48; }}
        .vendor-tag.dup {{ background: #ffecd2; color: #c56a15; }}
        .vendor-tag.none {{ background: #ffddd2; color: #c94a2a; }}
        .vendor-hint {{ font-size: 10px; margin-top: 2px; color: #a0a4b8; }}
    </style>
</head>
<body>

<div class="sidebar">
    <div class="logo">M</div>
    <div class="nav-item active" title="발주 자동화">
        <svg viewBox="0 0 24 24"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>
    </div>
    <div class="nav-item" title="설정">
        <svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
    </div>
</div>

<div class="main">
    <div class="top-header">
        <div class="board-title">
            <div class="icon">
                <svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
            </div>
            구매발주 자동화
        </div>
        <div class="user-info">
            <span>{today}</span>
            <div class="avatar" id="operator-avatar">?</div>
            <input class="cell-input" type="text" id="operator-name"
                   placeholder="담당자명 입력"
                   style="width:110px;font-weight:600;"
                   onchange="saveOperator()">
        </div>
    </div>

    <div class="toolbar">
        <button class="tool-btn primary" onclick="location.reload()">새로고침</button>
        <button class="tool-btn success" id="btn-register" onclick="registerAll()">확인 완료 → 아마란스 등록</button>
        <a href="/api/test-notification" target="_blank" class="tool-btn" style="text-decoration:none;border-color:#e85d4a;color:#e85d4a;" title="알람이 잘 오는지 테스트">🔔 알람 테스트</a>
        <div class="separator"></div>
        <div class="status-count">
            <div class="status-dot dot-pending"></div>
            <span>확인 요청 <strong id="pending-count">{len(pending_orders)}</strong></span>
        </div>
        <div class="status-count">
            <div class="status-dot" style="background:#a78bfa;"></div>
            <span>등록 완료 <strong>{len(reg_display)}</strong></span>
        </div>
        <div class="status-count">
            <div class="status-dot dot-confirmed"></div>
            <span>확인 <strong id="confirmed-count">0</strong></span>
        </div>
    </div>

    <div class="board-content">
"""

    if error:
        html += f'<div class="empty-state"><h2>오류 발생</h2><p>{error}</p></div>'
    elif not pending_orders and not reg_display:
        html += '<div class="empty-state"><h2>발주 대기 건이 없습니다</h2><p>먼데이닷컴에서 "요청 완료" 상태인 새 항목이 들어오면 여기에 표시됩니다.</p></div>'
    else:
        # ── 확인 요청 그룹 ──────────────────────────────────────
        if pending_orders:
            html += f"""
        <div class="group-header">
            <div class="group-color" style="background: #6a9bff;"></div>
            <span class="group-title" style="color: #6a9bff;">확인 요청</span>
            <span class="group-count">{len(pending_orders)}건</span>
        </div>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>품번</th>
                        <th>품명</th>
                        <th>요청수량</th>
                        <th>현재고</th>
                        <th>소진월</th>
                        <th>발주 요청일</th>
                        <th>입고 요청일</th>
                        <th>생산기지</th>
                        <th>입고처</th>
                        <th>요청 사유</th>
                        <th>요청자</th>
                        <th>거래처</th>
                        <th>비고</th>
                        <th>상태</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
"""
            for order in pending_orders:
                site_class = "pill-inhouse" if order['생산기지'] == '자사' else "pill-outsource"
                html += f"""
                    <tr id="row-{order['id']}" data-item-cd="{order['품번']}" data-qty="{order['요청수량']}" data-due="{order['입고요청일']}" data-itemnm="{order['품명']}" data-ingochu="{order['입고처']}">
                        <td class="item-code-cell">{order['품번']}</td>
                        <td>{order['품명']}</td>
                        <td style="font-weight:600;">{order['요청수량']}</td>
                        <td>{order['현재고'] or '-'}</td>
                        <td>{order['예상소진월'] or '-'}</td>
                        <td>{order['발주요청일']}</td>
                        <td>{order['입고요청일']}</td>
                        <td><span class="status-pill {site_class}">{order['생산기지']}</span></td>
                        <td>{order['입고처']}</td>
                        <td>{order['요청사유']}</td>
                        <td>{order['요청자']}</td>
                        <td>
                            <input class="vendor-input" type="text"
                                   id="vendor-{order['id']}"
                                   list="dl-{order['id']}"
                                   placeholder="거래처 검색/입력..."
                                   autocomplete="off">
                            <datalist id="dl-{order['id']}"></datalist>
                        </td>
                        <td><input class="cell-input" type="text" id="note-{order['id']}" placeholder="비고 입력"></td>
                        <td><span class="status-pill pill-pending" id="status-{order['id']}">대기</span></td>
                        <td>
                            <button class="row-btn row-btn-confirm" id="btn-{order['id']}" onclick="confirmOrder('{order['id']}')">확인</button><button class="row-btn row-btn-delete" onclick="dismissOrder('{order['id']}')">삭제</button>
                        </td>
                    </tr>
"""

            html += """
                </tbody>
            </table>
        </div>
"""
        else:
            html += '<div class="empty-state" style="padding:40px 20px;"><p style="color:#a0a4b8;">확인 요청 건이 없습니다.</p></div>'

        # ── 등록 완료 그룹 ──────────────────────────────────────
        if reg_display:
            collapsed = "true" if pending_orders else "false"
            html += f"""
        <div class="group-header" style="cursor:pointer;margin-top:8px;" onclick="toggleRegDone()">
            <div class="group-color" style="background: #a78bfa;"></div>
            <span class="group-title" style="color: #a78bfa;">등록 완료</span>
            <span class="group-count">{len(reg_display)}건</span>
            <span id="reg-toggle-icon" style="margin-left:auto;color:#a0a4b8;font-size:13px;">{"▶ 펼치기" if pending_orders else "▼ 접기"}</span>
        </div>
        <div id="reg-done-section" style="display:{'none' if pending_orders else 'block'};">
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>발주번호</th>
                        <th>품번</th>
                        <th>품명</th>
                        <th>요청수량</th>
                        <th>입고 요청일</th>
                        <th>거래처</th>
                        <th>등록일시</th>
                        <th>상태</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
"""
            for r in reg_display:
                po_no = r.get("po_no", "")
                html += f"""
                    <tr style="opacity:0.75;">
                        <td style="font-size:12px;color:#6246ea;font-weight:600;">{po_no or '-'}</td>
                        <td class="item-code-cell">{r['품번']}</td>
                        <td>{r['품명']}</td>
                        <td>{r['요청수량']}</td>
                        <td>{r['입고요청일']}</td>
                        <td>{r['거래처']}</td>
                        <td style="font-size:12px;color:#7a7f9a;">{r['registered_at']}</td>
                        <td><span class="status-pill pill-done">등록완료</span></td>
                        <td><button class="row-btn" style="background:#ffddd2;color:#c94a2a;font-size:12px;" onclick="cancelOrder('{r['id']}','{po_no}','{r['품번']}')">발주취소</button></td>
                    </tr>
"""
            html += """
                </tbody>
            </table>
        </div>
        </div>
"""

    # ── 작업 로그 (감사 기록) ──────────────────────────────
    if audit_entries:
        html += """
        <div class="group-header" style="cursor:pointer;margin-top:8px;" onclick="toggleAuditLog()">
            <div class="group-color" style="background: #f0b429;"></div>
            <span class="group-title" style="color: #d69e1a;">작업 로그</span>
            <span class="group-count">최근 """ + str(len(audit_entries)) + """건</span>
            <span id="audit-toggle-icon" style="margin-left:auto;color:#a0a4b8;font-size:13px;">▶ 펼치기</span>
        </div>
        <div id="audit-log-section" style="display:none;">
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr><th>시간</th><th>담당자</th><th>작업</th><th>내용</th></tr>
                </thead>
                <tbody>
"""
        for a in audit_entries:
            action_color = {"삭제": "#c94a2a", "발주취소": "#c94a2a", "발주등록 요청": "#2e7d32"}.get(a["작업"], "#444")
            html += f"""
                    <tr style="font-size:12px;">
                        <td style="color:#7a7f9a;white-space:nowrap;">{a['time']}</td>
                        <td style="font-weight:600;">{a['담당자']}</td>
                        <td style="color:{action_color};font-weight:600;white-space:nowrap;">{a['작업']}</td>
                        <td>{a['내용']}</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
        </div>
        </div>
"""

    html += f"""
    </div>
    <div class="summary-bar">
        <div class="summary-item">
            <span class="s-label">확인 요청</span>
            <span class="s-value pending" id="sum-pending">{len(pending_orders)}</span>
        </div>
        <div class="summary-item">
            <span class="s-label">확인 완료</span>
            <span class="s-value confirmed" id="sum-confirmed">0</span>
        </div>
        <div class="summary-item">
            <span class="s-label">등록 완료</span>
            <span class="s-value" style="color:#6246ea;" id="sum-registered">{len(reg_display)}</span>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
    const VENDOR_MAP = {vendor_json};
    const VENDOR_DUPS = {dup_json};
    const ITEM_VENDORS = {item_vendors_json};

    // 페이지 로드 시 거래처 매핑 적용
    document.addEventListener('DOMContentLoaded', () => {{
        document.querySelectorAll('tr[data-item-cd]').forEach(row => {{
            const itemCd = row.dataset.itemCd;
            const input = row.querySelector('.vendor-input');
            const datalist = row.querySelector('datalist');
            if (!input || !datalist) return;

            const mapped = VENDOR_MAP[itemCd];
            const dups = VENDOR_DUPS[itemCd];
            const allVendors = ITEM_VENDORS[itemCd] || [];

            // datalist에 이 품번의 모든 이력 거래처 추가
            allVendors.forEach(v => {{
                const opt = document.createElement('option');
                opt.value = v;
                datalist.appendChild(opt);
            }});

            if (dups && dups.length > 1) {{
                // 중복 거래처 — 주황 표시, 첫 번째 선택
                input.value = mapped || dups[0];
                input.className = 'vendor-input warn';
                input.title = `거래처가 ${{dups.length}}개입니다. 확인해주세요: ${{dups.join(', ')}}`;
            }} else if (mapped) {{
                // 단일 자동 매핑 — 초록
                input.value = mapped;
                input.className = 'vendor-input mapped';
                input.title = '자동 매핑됨. 변경 가능합니다.';
            }} else {{
                // 이력 없음 — 빨강
                input.value = '';
                input.className = 'vendor-input unmapped';
                input.title = '발주 이력이 없습니다. 직접 입력해주세요.';
            }}

            // 사용자가 값 변경 시 색상 업데이트
            input.addEventListener('input', () => {{
                if (input.value) {{
                    input.classList.remove('warn', 'unmapped');
                    input.classList.add('mapped');
                }} else {{
                    input.classList.remove('mapped');
                    input.classList.add('unmapped');
                }}
            }});
        }});
    }});

    // 담당자명: localStorage에 기억, 작업 시 필수
    document.addEventListener('DOMContentLoaded', () => {{
        const saved = localStorage.getItem('operatorName') || '';
        const input = document.getElementById('operator-name');
        input.value = saved;
        updateAvatar(saved);
    }});

    function saveOperator() {{
        const name = document.getElementById('operator-name').value.trim();
        localStorage.setItem('operatorName', name);
        updateAvatar(name);
        if (name) showToast('담당자: ' + name);
    }}

    function updateAvatar(name) {{
        document.getElementById('operator-avatar').textContent = name ? name.charAt(0) : '?';
    }}

    function getOperator() {{
        const name = document.getElementById('operator-name').value.trim();
        if (!name) {{
            showToast('먼저 우측 상단에 담당자명을 입력해주세요!', true);
            document.getElementById('operator-name').focus();
            return null;
        }}
        return name;
    }}

    function showToast(msg, isError) {{
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.className = isError ? 'toast error show' : 'toast show';
        setTimeout(() => t.className = 'toast', 3000);
    }}

    function updateCounts() {{
        const pending = document.querySelectorAll('.pill-pending').length;
        const confirmed = document.querySelectorAll('.pill-confirmed').length;
        document.getElementById('pending-count').textContent = pending;
        document.getElementById('confirmed-count').textContent = confirmed;
        document.getElementById('sum-pending').textContent = pending;
        document.getElementById('sum-confirmed').textContent = confirmed;
    }}

    function confirmOrder(id) {{
        const row = document.getElementById('row-' + id);
        const vendor = document.getElementById('vendor-' + id);
        const status = document.getElementById('status-' + id);
        const btn = document.getElementById('btn-' + id);

        // 거래처 미입력 체크
        if (!vendor.value.trim()) {{
            showToast('거래처를 입력해주세요: ' + row.dataset.itemCd, true);
            vendor.focus();
            return;
        }}

        // 확인 시 거래처 값 고정 저장
        row.dataset.vendor = vendor.value.trim();

        status.textContent = '확인';
        status.className = 'status-pill pill-confirmed';
        btn.textContent = '완료';
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'default';
        vendor.disabled = true;

        updateCounts();
        showToast('확인 완료: ' + row.dataset.itemCd + ' / ' + row.dataset.vendor);
    }}

    async function dismissOrder(id) {{
        const operator = getOperator();
        if (!operator) return;
        const row = document.getElementById('row-' + id);
        if (!confirm('이 발주 요청을 삭제할까요?\\n품번: ' + row.dataset.itemCd + '\\n담당자: ' + operator + '\\n(삭제하면 아마란스 발주 등록이 진행되지 않습니다)')) return;
        try {{
            const resp = await fetch('/api/dismiss-order', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{id: id, 품번: row.dataset.itemCd, 담당자: operator}}),
            }});
            const data = await resp.json();
            if (!data.ok) throw new Error(data.error || '실패');
            row.remove();
            updateCounts();
            showToast('삭제 완료 — 발주가 진행되지 않습니다.');
        }} catch (e) {{
            showToast('삭제 실패: ' + e.message, true);
        }}
    }}

    async function registerAll() {{
        const operator = getOperator();
        if (!operator) return;
        const confirmed = document.querySelectorAll('.pill-confirmed');
        if (confirmed.length === 0) {{
            showToast('먼저 항목을 확인해주세요.', true);
            return;
        }}

        const orders = [];
        confirmed.forEach(pill => {{
            const id = pill.id.replace('status-', '');
            const row = document.getElementById('row-' + id);
            orders.push({{
                id: id,
                품번: row.dataset.itemCd,
                요청수량: row.dataset.qty,
                입고요청일: row.dataset.due,
                거래처: row.dataset.vendor,   // 확인 시 저장된 거래처 사용
                비고: document.getElementById('note-' + id).value,
                입고처: row.dataset.ingochu || '',
            }});
        }});

        showToast('아마란스 등록 요청 중...');
        try {{
            const resp = await fetch('/api/register', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{orders, 담당자: operator}}),
            }});
            const data = await resp.json();
            showToast(data.message + ' — 잠시 후 새로고침됩니다.');

            // 상태 업데이트
            confirmed.forEach(pill => {{
                pill.textContent = '등록중';
                pill.className = 'status-pill pill-registering';
            }});
            setTimeout(() => location.reload(), 2000);
        }} catch (e) {{
            showToast('등록 실패: ' + e.message, true);
        }}
    }}

    // 발주 취소 (등록완료 그룹에서 제거 + 아마란스 삭제)
    async function cancelOrder(id, poNo, itemCd) {{
        const operator = getOperator();
        if (!operator) return;
        const msg = poNo
            ? itemCd + ' (' + poNo + ') 발주를 취소하시겠습니까?\\n아마란스에서도 자동 삭제됩니다.'
            : itemCd + ' 발주를 취소하시겠습니까?\\n(발주번호 미저장 — 아마란스에서 수동 삭제 필요)';
        if (!confirm(msg)) return;
        const resp = await fetch('/api/cancel-order', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{id, po_no: poNo, 담당자: operator}}),
        }});
        const data = await resp.json();
        if (data.ok) {{
            showToast(poNo ? '발주 취소 처리 및 아마란스 삭제 중...' : '발주 취소 처리됐습니다.');
            setTimeout(() => location.reload(), 1500);
        }}
    }}

    // 등록완료로 수동 이동
    async function markDone(id) {{
        const row = document.getElementById('row-' + id);
        const vendor = document.getElementById('vendor-' + id);
        await fetch('/api/mark-registered', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{orders: [{{
                id: id,
                품번: row.dataset.itemCd,
                요청수량: row.dataset.qty,
                입고요청일: row.dataset.due,
                거래처: vendor ? vendor.value : '',
            }}]}}),
        }});
        showToast(row.dataset.itemCd + ' 등록완료 처리됐습니다.');
        setTimeout(() => location.reload(), 1200);
    }}

    // 등록완료 그룹 접기/펼치기
    function toggleAuditLog() {{
        const sec = document.getElementById('audit-log-section');
        const icon = document.getElementById('audit-toggle-icon');
        if (!sec) return;
        if (sec.style.display === 'none') {{
            sec.style.display = 'block';
            if (icon) icon.textContent = '▼ 접기';
        }} else {{
            sec.style.display = 'none';
            if (icon) icon.textContent = '▶ 펼치기';
        }}
    }}

    function toggleRegDone() {{
        const sec = document.getElementById('reg-done-section');
        const icon = document.getElementById('reg-toggle-icon');
        if (!sec) return;
        if (sec.style.display === 'none') {{
            sec.style.display = 'block';
            if (icon) icon.textContent = '▼ 접기';
        }} else {{
            sec.style.display = 'none';
            if (icon) icon.textContent = '▶ 펼치기';
        }}
    }}

    // 알람음 (짧은 비프)
    function playBeep() {{
        try {{
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.type = 'sine'; osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.4, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
            osc.start(ctx.currentTime); osc.stop(ctx.currentTime + 0.6);
        }} catch(e) {{}}
    }}

    // 30초마다 먼데이닷컴 변경 감지 (신규 + 수정 모두) → 새로고침 + 비프음
    let _knownIds = new Set([...document.querySelectorAll('tr[data-item-cd]')].map(r => r.id.replace('row-', '')));
    let _dataFP = null;

    function _makeFP(orders) {{
        return orders
            .map(o => [o.id, o.품번, o.요청수량, o.입고요청일, o.발주요청일, o.입고처, o.생산기지, o.요청사유].join('|'))
            .sort()
            .join('||');
    }}

    setInterval(async () => {{
        try {{
            const resp = await fetch('/api/orders');
            if (!resp.ok) return;
            const orders = await resp.json();
            const fp = _makeFP(orders);
            if (_dataFP === null) {{ _dataFP = fp; return; }}
            if (fp !== _dataFP) {{
                _dataFP = fp;
                const hasNew = orders.some(o => !_knownIds.has(String(o.id)));
                try {{ playBeep(); }} catch(e) {{}}
                showToast(hasNew
                    ? '🔔 새 발주 요청이 들어왔습니다! 목록을 갱신합니다.'
                    : '📝 먼데이닷컴 발주 내용이 수정되었습니다. 목록을 갱신합니다.');
                setTimeout(() => location.reload(), 3000);
            }}
        }} catch(e) {{}}
    }}, 30000);

    // 5분마다 자동 새로고침 (최신 상태 유지)
    setInterval(() => location.reload(), 300000);
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
