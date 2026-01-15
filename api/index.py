# -*- coding: utf-8 -*-
"""
NgânMiu.Store - Check Cookie API (Vercel)
✅ Added Google Sheet ID key activation
- Store keys in KEY_DB_SHEET_ID -> tab "KeyGGSheet"
- Columns: STT | Google Sheet ID | Trạng Thái (Chưa Kích / Kích Hoạt)
- Each sheet_id is checked with TTL cache (default 60 minutes, best-effort)
"""

import os, time, json, random
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import requests

# ---- Google Sheets (KeyGGSheet) ----
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ---- Key check cache (best-effort) ----
_KEY_TTL_SECONDS = int(os.getenv('KEY_TTL_SECONDS', '3600'))  # 60m default
_key_cache = {}  # sheet_id -> {'ts': epoch, 'active': bool}

# =======================
# Config
# =======================
UA = os.getenv("SHOPEE_UA", "Android app Shopee appver=28320 app_type=1")
BASE = os.getenv("SHOPEE_BASE", "https://shopee.vn/api/v4")
POST_TIMEOUT = float(os.getenv("POST_TIMEOUT", "8"))

# Key database sheet (central)
KEY_DB_SHEET_ID = os.getenv("KEY_DB_SHEET_ID", "").strip()

# Service account JSON in env (recommended on Vercel)
# Put raw JSON string into GOOGLE_SERVICE_ACCOUNT_JSON env var
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

# Message when not activated
NOT_ACTIVE_MSG = os.getenv(
    "NOT_ACTIVE_MSG",
    "Key chưa kích hoạt vui lòng liên hệ zalo : 0819-555-000"
)

# best-effort daily cache (serverless may reset on cold start)
_daily_key_cache = {}  # sheet_id -> {"date":"YYYY-MM-DD","active":bool}

def _today_key():
    # use Asia/Ho_Chi_Minh like VN local date; approximate by UTC+7
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    vn = now.astimezone(timezone.utc).timestamp() + 7*3600
    dt = datetime.utcfromtimestamp(vn)
    return dt.strftime("%Y-%m-%d")

def _make_gspread_client():
    if not KEY_DB_SHEET_ID:
        raise RuntimeError("Missing KEY_DB_SHEET_ID in env.")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in env.")

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _ensure_key_sheet(ws):
    # Ensure headers + dropdown validation (best-effort)
    headers = ["STT", "Google Sheet ID", "Trạng Thái"]
    try:
        first = ws.row_values(1)
        if [c.strip() for c in first[:3]] != headers:
            ws.update("A1:C1", [headers])
            ws.format("A1:C1", {"textFormat": {"bold": True}})
    except Exception:
        pass

def _get_or_create_key_worksheet(gc):
    sh = gc.open_by_key(KEY_DB_SHEET_ID)

    try:
        ws = sh.worksheet("KeyGGSheet")
    except Exception:
        ws = sh.add_worksheet(title="KeyGGSheet", rows=2000, cols=5)
    _ensure_key_sheet(ws)
    return ws

def _normalize_status(s: str) -> str:
    t = (s or "").strip()
    # accept variants
    if t.lower().replace(" ", "") in ["kichhoat", "kíchhoạt", "kíchhoat", "active", "activated"]:
        return "Kích Hoạt"
    return "Chưa Kích"

def check_sheet_key_active(sheet_id: str):
    """
    Returns: (active: bool, note: str)
    - If sheet_id not found: create row with Chưa Kích
    - Cache best-effort once/day per sheet_id
    """
    sheet_id = (sheet_id or "").strip()
    if not sheet_id:
        return False, "Missing sheet_id"

    now = int(time.time())
    cached = _key_cache.get(sheet_id)
    if cached and (now - int(cached.get("ts", 0))) < _KEY_TTL_SECONDS:
        return bool(cached.get("active")), "cached"

    try:
        gc = _make_gspread_client()
        ws = _get_or_create_key_worksheet(gc)

        # Find sheet_id in column B
        col_b = ws.col_values(2)  # includes header
        row_idx = None
        for i, v in enumerate(col_b[1:], start=2):
            if (v or "").strip() == sheet_id:
                row_idx = i
                break

        if row_idx is None:
            # append new row
            stt = len(col_b)  # header included
            ws.append_row([stt, sheet_id, "Chưa Kích"])
            active = False
        else:
            status = ws.cell(row_idx, 3).value
            status_norm = _normalize_status(status)
            if status_norm != status:
                try:
                    ws.update_cell(row_idx, 3, status_norm)
                except Exception:
                    pass
            active = (status_norm == "Kích Hoạt")

        _key_cache[sheet_id] = {"ts": int(time.time()), "active": active}
        return active, "ok"
    except Exception as e:
        # If key-check fails due to quota/timeout, be safe: deny
        _key_cache[sheet_id] = {"ts": int(time.time()), "active": False}
        return False, f"key_check_error: {e}"

# =======================
# Helpers
# =======================
def pick_fp(cookie: str):
    # keep for future fingerprint usage
    return ""

def _safe_get(d, path, default=""):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default

def _format_vnd(n):
    try:
        return f"{int(n):,}".replace(",", ".") + " đ"
    except Exception:
        return ""

def parse_order_obj(order_obj):
    """
    Map Shopee order detail -> flat schema used by Google Apps Script
    """
    if not isinstance(order_obj, dict):
        return None

    tracking_no = order_obj.get("tracking_no") or order_obj.get("tracking_number") or ""
    status_text = order_obj.get("status_text") or order_obj.get("status") or ""

    shipping_name = order_obj.get("shipping_name") or _safe_get(order_obj, ["address", "shipping_name"], "")
    shipping_phone = order_obj.get("shipping_phone") or _safe_get(order_obj, ["address", "shipping_phone"], "")
    shipping_address = order_obj.get("shipping_address") or _safe_get(order_obj, ["address", "shipping_address"], "")

    shipper_name = order_obj.get("shipper_name") or _safe_get(order_obj, ["shipping", "shipper_name"], "")
    shipper_phone = order_obj.get("shipper_phone") or _safe_get(order_obj, ["shipping", "shipper_phone"], "")

    product_name = order_obj.get("product_name") or ""
    product_image = order_obj.get("product_image") or ""

    cod_amount = order_obj.get("cod_amount")
    cod_display = order_obj.get("cod_display")
    if cod_amount is None:
        # fallback from info_card.final_total if present (rare)
        ft = _safe_get(order_obj, ["info_card", "final_total"], None)
        if isinstance(ft, (int, float)) and ft > 0:
            # some schemas have *100000 inflation
            cod_amount = int(ft // 100000)
    if cod_display is None and cod_amount not in (None, ""):
        cod_display = _format_vnd(cod_amount)

    shop_id = order_obj.get("shop_id") or ""
    shop_username = order_obj.get("shop_username") or order_obj.get("username") or ""

    return {
        "tracking_no": tracking_no,
        "status_text": status_text,
        "shipping_name": shipping_name,
        "shipping_phone": shipping_phone,
        "shipping_address": shipping_address,
        "shipper_name": shipper_name,
        "shipper_phone": shipper_phone,
        "product_name": product_name,
        "product_image": product_image,
        "cod_amount": cod_amount if cod_amount is not None else "",
        "cod_display": cod_display or "",
        "shop_id": shop_id,
        "shop_username": shop_username,
        "timeline_preview": order_obj.get("timeline_preview") or [],
        "timeline_full": order_obj.get("timeline_full") or [],
    }

# =======================
# Shopee fetch
# =======================
def shopee_headers(cookie: str):
    return {
        "user-agent": UA,
        "accept": "application/json",
        "content-type": "application/json",
        "cookie": cookie or "",
        "referer": "https://shopee.vn/",
    }

def fetch_orders_list(cookie: str, list_limit: int = 5):
    # This endpoint name can vary; keep generic pattern
    # Using a common one for order list:
    url = f"{BASE}/order/get_all_order_and_checkout_list"
    payload = {
        "limit": int(list_limit),
        "offset": 0
    }
    r = requests.post(url, headers=shopee_headers(cookie), json=payload, timeout=POST_TIMEOUT)
    return r.status_code, r.text

def fetch_order_detail(cookie: str, order_id: int):
    # Typical endpoint for order detail:
    url = f"{BASE}/order/get_order_detail"
    payload = {"order_id": int(order_id)}
    r = requests.post(url, headers=shopee_headers(cookie), json=payload, timeout=POST_TIMEOUT)
    return r.status_code, r.text

def extract_order_ids(list_json):
    """
    Try multiple possible paths to get order ids.
    """
    if not isinstance(list_json, dict):
        return []
    # Common patterns:
    # data.order_list or data.orders
    data = list_json.get("data") or {}
    ids = []

    # pattern A: data.order_list (list of dict with order_id)
    ol = data.get("order_list")
    if isinstance(ol, list):
        for x in ol:
            oid = x.get("order_id") if isinstance(x, dict) else None
            if isinstance(oid, int):
                ids.append(oid)

    # pattern B: data.orders
    od = data.get("orders")
    if isinstance(od, list):
        for x in od:
            oid = x.get("order_id") if isinstance(x, dict) else None
            if isinstance(oid, int):
                ids.append(oid)

    # pattern C: data.order_cards
    cards = data.get("order_cards")
    if isinstance(cards, list):
        for c in cards:
            oid = c.get("order_id") if isinstance(c, dict) else None
            if isinstance(oid, int):
                ids.append(oid)

    # unique keep order
    seen = set()
    out = []
    for oid in ids:
        if oid not in seen:
            seen.add(oid)
            out.append(oid)
    return out

# =======================
# Routes
# =======================
@app.get("/api/ping")
def ping():
    return jsonify({"ok": True})


@app.post("/api/request-activation")
def api_request_activation():
    """Register current Google Sheet ID into KeyGGSheet (create row if missing)."""
    body = request.get_json(silent=True) or {}
    sheet_id = (body.get("sheet_id") or "").strip()
    sheet_name = (body.get("sheet_name") or "").strip()

    if not sheet_id:
        return jsonify({"ok": False, "message": "Missing sheet_id"}), 400

    try:
        gc = _make_gspread_client()
        ws = _get_or_create_key_worksheet(gc)

        # Find in column B
        col_b = ws.col_values(2)
        row_idx = None
        for i, v in enumerate(col_b[1:], start=2):
            if (v or "").strip() == sheet_id:
                row_idx = i
                break

        if row_idx is None:
            stt = len(col_b)
            ws.append_row([stt, sheet_id, "Chưa Kích"], value_input_option="USER_ENTERED")
            row_idx = stt + 1

        # optional: update a note/name in col D if you later add it
        msg = "Đã gửi yêu cầu kích hoạt"
        if sheet_name:
            msg += f" ({sheet_name})"
        return jsonify({"ok": True, "message": msg, "row": row_idx})
    except Exception as e:
        return jsonify({"ok": False, "message": "Key DB error", "detail": str(e)}), 500


@app.post("/api/check-cookie")
def check_cookie():
    body = request.get_json(silent=True) or {}
    cookie = (body.get("cookie") or "").strip()
    sheet_id = (body.get("sheet_id") or body.get("google_sheet_id") or "").strip()
    list_limit = int(body.get("list_limit") or 5)
    max_orders = int(body.get("max_orders") or 4)

    # ---- Key gate ----
    active, note = check_sheet_key_active(sheet_id)
    if not active:
        return jsonify({
            "count": 0,
            "error": 1,
            "message": NOT_ACTIVE_MSG,
            "data": None,
            "data_list": []
        }), 200

    if not cookie:
        return jsonify({"error": 1, "message": "Missing cookie", "count": 0, "data": None, "data_list": []}), 400

    # ---- Fetch list ----
    try:
        code, text = fetch_orders_list(cookie, list_limit=list_limit)
        if code < 200 or code >= 300:
            return jsonify({"error": 1, "message": f"HTTP {code}", "raw": text[:500]}), 200

        try:
            j = json.loads(text)
        except Exception:
            return jsonify({"error": 1, "message": "Invalid JSON list"}), 200

        order_ids = extract_order_ids(j)
        if not order_ids:
            # alive but no orders
            return jsonify({"count": 0, "data": None, "data_list": []}), 200

        order_ids = order_ids[:max_orders]

        data_list = []
        for oid in order_ids:
            d_code, d_text = fetch_order_detail(cookie, oid)
            if d_code < 200 or d_code >= 300:
                continue
            try:
                d_j = json.loads(d_text)
            except Exception:
                continue
            # try common paths
            obj = (d_j.get("data") or d_j.get("order") or {})
            mapped = parse_order_obj(obj)
            if mapped and mapped.get("tracking_no"):
                data_list.append(mapped)

        if not data_list:
            return jsonify({"count": 0, "data": None, "data_list": []}), 200

        return jsonify({
            "count": len(data_list),
            "data": data_list[0],
            "data_list": data_list
        }), 200

    except Exception as e:
        return jsonify({"error": 1, "message": f"server_error: {e}", "count": 0, "data": None, "data_list": []}), 200
