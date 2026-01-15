# -*- coding: utf-8 -*-
"""
NgânMiu.Store - Cookie Check API (Vercel Ready)
✅ Endpoints:
  - GET  /api/ping
  - POST /api/check-cookie

Mặc định:
  - list_limit = 5 (lấy tối đa 5 order_id đầu)
  - max_orders = 4 (trả tối đa 4 đơn hợp lệ)
"""

from flask import Flask, request, jsonify
import requests, re
from collections import deque
from datetime import datetime

# ========= Flask =========
app = Flask(__name__)

# ========= Shopee API config =========
UA   = "Android app Shopee appver=28320 app_type=1"
BASE = "https://shopee.vn/api/v4"

DEFAULT_LIST_LIMIT = 5
DEFAULT_MAX_ORDERS = 4

# ================= HTTP =================
def build_headers(cookie: str) -> dict:
    return {
        "User-Agent": UA,
        "Cookie": cookie.strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://shopee.vn/",
    }

def http_get(url: str, headers: dict, params: dict | None = None, timeout: int = 12):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        if "application/json" in (r.headers.get("Content-Type") or ""):
            return r.status_code, r.json()
        return r.status_code, {"raw": r.text}
    except requests.RequestException as e:
        return 0, {"error": str(e)}

# ================= JSON helpers =================
def find_first_key(data, key):
    dq = deque([data])
    while dq:
        cur = dq.popleft()
        if isinstance(cur, dict):
            if key in cur:
                return cur[key]
            dq.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            dq.extend(x for x in cur if isinstance(x, (dict, list)))
    return None

def bfs_values_by_key(data, target_keys=("order_id",)):
    out, dq, tset = [], deque([data]), set(target_keys)
    while dq:
        cur = dq.popleft()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in tset:
                    out.append(v)
                if isinstance(v, (dict, list)):
                    dq.append(v)
        elif isinstance(cur, list):
            dq.extend(cur)
    return out

def as_text(val):
    if isinstance(val, dict):
        return (
            val.get("text") or val.get("label") or val.get("value") or val.get("desc")
            or val.get("title") or val.get("subtitle") or val.get("sub_title")
            or val.get("tip") or val.get("tips")
        )
    if isinstance(val, list) and val:
        f = val[0]
        if isinstance(f, dict):
            return (
                f.get("text") or f.get("label") or f.get("value") or f.get("desc")
                or f.get("title") or f.get("subtitle") or f.get("sub_title")
                or f.get("tip") or f.get("tips")
            )
        if isinstance(f, str):
            return f
    return val

def normalize_image_url(s):
    if not isinstance(s, str) or not s:
        return None
    s = s.strip()
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/file/"):
        return "https://cf.shopee.vn" + s
    if s.startswith("http"):
        return s
    if re.fullmatch(r"[A-Za-z0-9\-_]{20,}", s):
        return f"https://cf.shopee.vn/file/{s}"
    return s

def fmt_ts(ts):
    if isinstance(ts, str) and ts.isdigit():
        ts = int(ts)
    if isinstance(ts, (int, float)) and ts > 1_000_000:
        try:
            return datetime.fromtimestamp(int(ts)).strftime("%H:%M %d-%m-%Y")
        except Exception:
            return str(ts)
    return str(ts) if ts is not None else None

def normalize_status_text(status: str) -> str:
    if not isinstance(status, str):
        return ""
    s = status.strip()
    s = re.sub(r"^tình trạng\s*:?\s*", "", s, flags=re.I)
    s = re.sub(r"^[\s\N{VARIATION SELECTOR-16}\uFE0F\U0001F300-\U0001FAFF]+", "", s)
    return s.strip()

def is_shopee_processing_text(status: str) -> bool:
    s = normalize_status_text(status).lower()
    return bool(
        re.search(r"đơn\s*hàng.*đang.*(được)?\s*xử lý.*shopee", s)
        or re.search(r"processing.*by.*shopee", s)
    )

# ================= Status map (Shopee CODE MAP) =================
CODE_MAP = {
    "order_status_text_to_receive_delivery_done": ("✅ Giao hàng thành công", "success"),
    "order_tooltip_to_receive_delivery_done":     ("✅ Giao hàng thành công", "success"),
    "label_order_delivered":                      ("✅ Giao hàng thành công", "success"),
    "order_list_text_to_receive_non_cod":         ("🚚 Đang chờ nhận", "info"),
    "label_to_receive":                           ("🚚 Đang chờ nhận", "info"),
    "label_order_to_receive":                     ("🚚 Đang chờ nhận", "info"),
    "label_order_to_ship":                        ("📦 Chờ giao hàng", "warning"),
    "label_order_being_packed":                   ("📦 Đang chuẩn bị", "warning"),
    "label_order_processing":                     ("🔄 Đang xử lý", "warning"),
    "label_order_paid":                           ("💰 Đã thanh toán", "info"),
    "label_order_unpaid":                         ("💸 Chưa thanh toán", "info"),
    "label_order_waiting_shipment":               ("📦 Chờ bàn giao", "info"),
    "label_order_shipped":                        ("🚛 Đã bàn giao", "info"),
    "label_order_delivery_failed":                ("❌ Giao thất bại", "danger"),
    "label_order_cancelled":                      ("❌ Đã hủy", "danger"),
    "label_order_return_refund":                  ("↩️ Trả hàng", "info"),
    "order_list_text_to_ship_ship_by_date_not_calculated": ("🎖 Chờ duyệt", "warning"),
    "order_status_text_to_ship_ship_by_date_not_calculated": ("🎖 Chờ duyệt", "warning"),
    "label_ship_by_date_not_calculated": ("🎖 Chờ duyệt", "warning"),
    "label_preparing_order": ("📦 Chờ shop gửi", "warning"),
    "order_list_text_to_ship_order_shipbydate": ("📦 Chờ shop gửi", "warning"),
    "order_status_text_to_ship_order_shipbydate": ("📦 Chuẩn bị hàng", "warning"),
    "order_list_text_to_ship_order_shipbydate_cod": ("📦 Chờ shop gửi", "warning"),
    "order_status_text_to_ship_order_shipbydate_cod": ("📦 Chờ shop gửi", "warning"),
    "order_status_text_to_ship_order_edt_cod": ("📦 Chờ shop gửi", "warning"),
    "order_status_text_to_ship_order_edt_cod_range": ("📦 Chờ duyệt", "warning"),
}

def map_code(code):
    if not isinstance(code, str):
        return None, "secondary"
    return CODE_MAP.get(code, (code, "secondary"))

# ================= Cancel helpers =================
def tree_contains_str(data, target: str) -> bool:
    if isinstance(data, dict):
        for v in data.values():
            if tree_contains_str(v, target):
                return True
    elif isinstance(data, list):
        for v in data:
            if tree_contains_str(v, target):
                return True
    elif isinstance(data, str):
        return data == target
    return False

def is_buyer_cancelled(detail_raw: dict) -> bool:
    d = detail_raw if isinstance(detail_raw, dict) else {}
    if tree_contains_str(d, "order_status_text_cancelled_by_buyer"):
        return True

    who = (
        find_first_key(d, "cancel_by")
        or find_first_key(d, "canceled_by")
        or find_first_key(d, "cancel_user_role")
        or find_first_key(d, "initiator")
        or find_first_key(d, "operator_role")
        or find_first_key(d, "operator")
    )
    if isinstance(who, dict):
        who = as_text(who)
    who_s = (str(who or "")).lower()

    reason = (
        find_first_key(d, "cancel_reason")
        or find_first_key(d, "buyer_cancel_reason")
        or find_first_key(d, "cancel_desc")
        or find_first_key(d, "cancel_description")
        or find_first_key(d, "reason")
    )
    if isinstance(reason, dict):
        reason = as_text(reason)
    reason_s = (str(reason or "")).lower()

    status_label = (as_text(find_first_key(d, "status_label")) or "").lower()
    is_cancel_status = (
        ("cancel" in status_label)
        or ("hủy" in status_label)
        or ("cancel" in reason_s)
        or ("hủy" in reason_s)
    )
    buyer_flags = ("buyer", "user", "customer", "người mua")

    if is_cancel_status and any(k in who_s or k in reason_s for k in buyer_flags):
        return True
    if "người mua" in reason_s and "hủy" in reason_s:
        return True
    return False

# ================= Fetch orders (LIST LIMIT = 5) =================
def fetch_orders_and_details(cookie: str, list_limit: int = DEFAULT_LIST_LIMIT, offset: int = 0):
    """
    list_limit=5 để nhẹ khi deploy Vercel.
    """
    headers = build_headers(cookie)
    list_url = f"{BASE}/order/get_all_order_and_checkout_list"

    _, data1 = http_get(list_url, headers, params={"limit": int(list_limit), "offset": int(offset)})
    order_ids = bfs_values_by_key(data1, ("order_id",)) if isinstance(data1, dict) else []

    # unique order_id
    seen, uniq = set(), []
    for oid in order_ids:
        if oid not in seen:
            seen.add(oid)
            uniq.append(oid)

    details = []
    for oid in uniq[: int(list_limit)]:
        detail_url = f"{BASE}/order/get_order_detail"
        _, data2 = http_get(detail_url, headers, params={"order_id": oid})
        details.append({"order_id": oid, "raw": data2})

    return {"details": details}

# ================= Extract COD =================
def extract_cod_amount(d) -> int:
    """
    Shopee thường trả amount theo đơn vị nhỏ (x100000)
    => giữ đúng logic của bạn: amount//100000
    """
    for key in ["final_total", "total_amount", "amount", "cod_amount", "buyer_total_amount"]:
        val = find_first_key(d, key)
        if val is not None:
            try:
                amount = int(val) if isinstance(val, (int, float, str)) else 0
                if amount > 0:
                    return amount // 100000
            except Exception:
                pass
    info_card = find_first_key(d, "info_card")
    if isinstance(info_card, dict):
        for key in ["final_total", "total"]:
            val = info_card.get(key)
            if val:
                try:
                    return int(val) // 100000
                except Exception:
                    pass
    return 0

def format_currency(amount: int) -> str:
    if amount <= 0:
        return "0 đ"
    return f"{amount:,}".replace(",", ".") + " đ"

# ================= Timeline builder (rút gọn, giữ chất) =================
TIME_KEYS = ("time","ts","timestamp","ctime","create_time","update_time","event_time","log_time","happen_time","occur_time")
TEXT_KEYS = ("text","status","description","detail","message","desc","label","note","title","subtitle","sub_title","tip","tips","name","content","status_text","event","event_desc","status_desc","detail_desc")

def _pick_time(d):
    for k in TIME_KEYS:
        if isinstance(d, dict) and k in d and d[k] not in (None, "", []):
            return d[k]
    return None

def _deep_pick_text(obj):
    if isinstance(obj, dict):
        for k in TEXT_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            t = _deep_pick_text(v)
            if t:
                return t
    elif isinstance(obj, list):
        for it in obj:
            t = _deep_pick_text(it)
            if t:
                return t
    elif isinstance(obj, str):
        s = obj.strip()
        if s:
            return s
    return None

def _events_from_lists(obj):
    out = []
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                if isinstance(it, dict):
                    ts = _pick_time(it) or _pick_time({"_": it})
                    txt = _deep_pick_text(it)
                    if txt and (ts is not None):
                        out.append((ts, txt))
                walk(it)
    walk(obj)
    return out

def build_rich_timeline(d):
    raw = []
    raw += _events_from_lists(d)
    rows = []
    for ts, txt in raw:
        if txt and txt not in [r[1] for r in rows]:
            ts_val = fmt_ts(ts) if ts is not None else None
            rows.append((ts_val, txt))
    rows.sort(key=lambda x: x[0] if x[0] else "", reverse=True)
    p = rows[:3] if len(rows) > 3 else rows
    return p, rows

def first_image(obj):
    for k in ("image","img","thumb","thumbnail","cover","photo","pic","icon","product_image","item_image"):
        v = find_first_key(obj, k)
        if isinstance(v, str):
            return normalize_image_url(v)
        if isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    return normalize_image_url(x)
                if isinstance(x, dict):
                    for kk in ("url","image","thumbnail"):
                        u = x.get(kk)
                        if isinstance(u, str):
                            return normalize_image_url(u)
    items = find_first_key(obj, "card_item_list") or find_first_key(obj, "items")
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                for kk in ("image","thumbnail","cover","img"):
                    u = it.get(kk)
                    if isinstance(u, str):
                        return normalize_image_url(u)
    return None

def first_tracking_number(obj):
    for k in ("tracking_number","tracking_no","tracking_num","trackingid","waybill","waybill_no","awb","billcode","bill_code","consignment_no","cn_number","shipment_no"):
        v = find_first_key(obj, k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    tinfo = find_first_key(obj, "tracking_info")
    if isinstance(tinfo, dict):
        t = tinfo.get("tracking_number") or tinfo.get("tracking_no")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None

def build_status_text_and_color(d):
    # ưu tiên tracking_info
    tinfo = find_first_key(d, "tracking_info")
    if isinstance(tinfo, dict):
        desc = tinfo.get("description") or tinfo.get("text") or tinfo.get("status_text")
        if isinstance(desc, str) and desc.strip():
            desc_norm = normalize_status_text(desc)
            if "hủy" in desc_norm.lower() or "cancel" in desc_norm.lower():
                return desc_norm, "danger"
            if is_shopee_processing_text(desc):
                return "🎖 Shopee đang xử lý", "info"
            dl = desc_norm.lower()
            if (
                re.search(r"(chuẩn|chuan)\s*bi.*h(à|a)ng", dl)
                or re.search(r"ch(ờ|o)\s*shop\s*g(ử|u)i", dl)
                or re.search(r"người\s*g(ử|u)i\s*đang\s*chuẩn\s*bị\s*h(à|a)ng", dl)
                or re.search(r"(prepar|packing|to\s*ship|ready\s*to\s*ship)", dl)
            ):
                return desc_norm, "warning"
            if ("không" in dl or "fail" in dl or "failed" in dl or "unsuccess" in dl):
                return desc_norm, "danger"
            if (("giao hàng" in dl or "giao thành công" in dl or "delivered" in dl) and ("không" not in dl)):
                return desc_norm, "success"
            if any(kw in dl for kw in ["đang vận chuyển", "đang giao", "in transit", "out for delivery"]):
                return desc_norm, "info"
            return desc_norm, "info"

    status = find_first_key(d, "status") or {}
    if isinstance(status, dict):
        for code in [
            as_text(status.get("header_text")),
            as_text(status.get("list_view_text")),
            as_text(status.get("status_label")),
            as_text(status.get("list_view_status_label")),
        ]:
            if isinstance(code, str):
                if "processing" in code.lower():
                    return "🎖 Shopee đang xử lý", "info"
                t, c = map_code(code)
                if t:
                    return t, c

    code = as_text(find_first_key(d, "status_label")) or as_text(find_first_key(d, "list_view_status_label"))
    t, c = map_code(code)
    if isinstance(t, str) and is_shopee_processing_text(t):
        return "🎖 Shopee đang xử lý", "info"
    return t, c

def extract_shop_info(d):
    username = None
    shop_id = None
    si = find_first_key(d, "shop_info")
    if isinstance(si, dict):
        username = si.get("username") or username
        shop_id  = si.get("shop_id")  or shop_id
    return username, shop_id

def pick_columns_from_detail(detail_raw: dict) -> dict:
    d = detail_raw if isinstance(detail_raw, dict) else {}
    s = {}

    txt, col = build_status_text_and_color(d)
    s["status_text"]  = txt or "—"
    s["status_color"] = col or "secondary"

    cod_amount = extract_cod_amount(d)
    s["cod_amount"] = cod_amount
    s["cod_display"] = format_currency(cod_amount)

    rec_addr = find_first_key(d, "recipient_address") or {}
    if not isinstance(rec_addr, dict):
        rec_addr = {}

    s["shipping_address"] = find_first_key(d, "shipping_address") or rec_addr.get("full_address")
    s["shipping_name"]    = find_first_key(d, "shipping_name") or rec_addr.get("name") or find_first_key(d, "recipient_name")
    s["shipping_phone"]   = find_first_key(d, "shipping_phone") or rec_addr.get("phone")

    s["shipper_name"]     = find_first_key(d, "driver_name")
    s["shipper_phone"]    = find_first_key(d, "driver_phone")

    s["product_image"]    = normalize_image_url(find_first_key(d, "image")) or first_image(d)
    s["tracking_no"]      = first_tracking_number(d)
    s["shop_username"], s["shop_id"] = extract_shop_info(d)

    # Product name (đơn giản nhưng đủ ổn)
    product_name = None
    items = find_first_key(d, "items") or find_first_key(d, "card_item_list") or find_first_key(d, "order_items")
    if isinstance(items, list) and items:
        first_item = items[0]
        if isinstance(first_item, dict):
            product_name = (
                first_item.get("name")
                or first_item.get("item_name")
                or first_item.get("product_name")
                or first_item.get("model_name")
            )
    if not product_name:
        product_name = find_first_key(d, "product_name") or find_first_key(d, "item_name") or find_first_key(d, "name")

    s["product_name"] = product_name if isinstance(product_name, str) else None

    preview, full = build_rich_timeline(d)
    s["timeline_preview"] = preview
    s["timeline_full"] = full

    return s

# ================== Routes ==================
@app.get("/api/ping")
def api_ping():
    return jsonify({"ok": True})

@app.post("/api/check-cookie")
def api_check_cookie_single():
    """
    API check cookie cho Google Sheet / Apps Script
    - list_limit = 5 (nhẹ)
    - trả tối đa max_orders = 4 đơn hợp lệ

    Body JSON:
      {
        "cookie": "SPC_ST=....",
        "max_orders": 4        # optional
        "list_limit": 5        # optional
      }
    """
    data = request.get_json(silent=True) or {}
    cookie = (data.get("cookie") or "").strip()
    if not cookie:
        return jsonify({"error": "Missing cookie"}), 400

    # cho phép override (nếu bạn muốn)
    max_orders = data.get("max_orders", DEFAULT_MAX_ORDERS)
    list_limit = data.get("list_limit", DEFAULT_LIST_LIMIT)

    try:
        max_orders = max(1, min(int(max_orders), 10))
    except Exception:
        max_orders = DEFAULT_MAX_ORDERS

    try:
        list_limit = max(1, min(int(list_limit), 20))
    except Exception:
        list_limit = DEFAULT_LIST_LIMIT

    fetched = fetch_orders_and_details(cookie, list_limit=list_limit, offset=0)
    details = fetched.get("details", []) if isinstance(fetched, dict) else []

    picked = []
    for det in details:
        raw = det.get("raw") or {}
        # skip đơn bị buyer hủy
        if is_buyer_cancelled(raw):
            continue

        s = pick_columns_from_detail(raw)

        # đơn "hợp lệ" khi có tracking hoặc status khác rỗng
        if s.get("tracking_no") or (s.get("status_text") not in (None, "", "—")):
            picked.append(s)

        if len(picked) >= max_orders:
            break

    if not picked:
        # giữ đúng kiểu “cookie die” như bản gốc
        return jsonify({
            "data": None,
            "data_list": [],
            "count": 0,
            "message": "Cookie khóa/hết hạn hoặc không có đơn hợp lệ"
        })

    return jsonify({
        "data": picked[0],
        "data_list": picked,
        "count": len(picked)
    })

# Vercel needs "app" exported
# (this file is used as api/index.py)
