"""RPA → 웹 UI 붙여넣기 안내 신호"""

_state = {"active": False, "text": ""}


def set_paste_needed(text: str):
    _state["active"] = True
    _state["text"] = text


def clear_paste():
    _state["active"] = False
    _state["text"] = ""


def get_state() -> dict:
    return dict(_state)
