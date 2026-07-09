import os
from dotenv import load_dotenv

load_dotenv()

AMARANTH_URL = os.getenv("AMARANTH_URL", "https://amaranth.douzone.com")
AMARANTH_USER = os.getenv("AMARANTH_USER", "")
AMARANTH_PASS = os.getenv("AMARANTH_PASS", "")

AMARANTH_ACCESS_TOKEN = os.getenv("AMARANTH_ACCESS_TOKEN", "")
AMARANTH_HASH_KEY = os.getenv("AMARANTH_HASH_KEY", "")
AMARANTH_GROUP_SEQ = os.getenv("AMARANTH_GROUP_SEQ", "")
AMARANTH_CALLER_NAME = os.getenv("AMARANTH_CALLER_NAME", "")
AMARANTH_CO_CD = os.getenv("AMARANTH_CO_CD", "1000")

MONDAY_API_KEY = os.getenv("MONDAY_API_KEY", "")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID", "")
