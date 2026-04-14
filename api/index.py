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
import requests, re, time
from collections import deque
from datetime import datetime
from typing import Optional

# ========= Flask =========
app = Flask(__name__)

# ========= Shopee API config =========
UA   = "Android app Shopee appver=28320 app_type=1"
BASE = "https://shopee.vn/api/v4"
CHECK_URL = f"{BASE}/account/basic/get_account_info"
SHOPEE_CONFIRM_URL = f"{BASE}/order/action/confirm_order_delivered/"
SHOPEE_CONFIRM_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

DEFAULT_LIST_LIMIT = 5
DEFAULT_MAX_ORDERS = 4

# ================= HTTP =================
def sanitize_cookie(cookie: str) -> str:
    raw = str(cookie or "").strip()
    if not raw:
        return ""
    raw = raw.replace("\r", "\n").replace("\t", "")
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    parts = []
    for piece in re.split(r"[;\n]+", raw):
        item = piece.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        parts.append(f"{k}={v}")
    return "; ".join(parts)

def cookie_map(cookie: str) -> dict:
    out = {}
    for part in sanitize_cookie(cookie).split(";"):
        item = part.strip()
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        if k.strip():
            out[k.strip()] = v.strip()
    return out

def build_headers(cookie: str) -> dict:
    ck = sanitize_cookie(cookie)
    return {
        "User-Agent": UA,
        "Cookie": ck,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://shopee.vn/",
    }

def build_order_header_variants(cookie: str):
    ck = sanitize_cookie(cookie)
    ckm = cookie_map(ck)
    csrf = str(ckm.get("csrftoken") or ckm.get("CSRFTOKEN") or "").strip()

    v1 = build_headers(ck)
    v2 = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": ck,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://shopee.vn/",
        "X-API-SOURCE": "pc",
    }
    v3 = {
        **v2,
        "Origin": "https://shopee.vn",
        "X-Requested-With": "XMLHttpRequest",
    }
    if csrf:
        v3["x-csrftoken"] = csrf
        v3["X-CSRFToken"] = csrf

    return [v1, v2, v3]

def http_get(url: str, headers: dict, params: dict | None = None, timeout: int = 12):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        if "application/json" in (r.headers.get("Content-Type") or ""):
            return r.status_code, r.json()
        return r.status_code, {"raw": r.text}
    except requests.RequestException as e:
        return 0, {"error": str(e)}

def http_post(url: str, headers: dict, payload: dict | None = None, timeout: int = 12):
    try:
        r = requests.post(url, headers=headers, json=(payload or {}), timeout=timeout)
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
    variants = build_order_header_variants(cookie)
    list_url = f"{BASE}/order/get_all_order_and_checkout_list"

    list_status, data1 = 0, {}
    for headers in variants:
        list_status, data1 = http_get(list_url, headers, params={"limit": int(list_limit), "offset": int(offset)})
        if list_status == 200 and isinstance(data1, dict):
            break

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
        detail_status, data2 = 0, {}
        for headers in variants:
            detail_status, data2 = http_get(detail_url, headers, params={"order_id": oid})
            if detail_status == 200 and isinstance(data2, dict):
                break
        details.append({
            "order_id": oid,
            "http_status": detail_status,
            "raw": data2
        })

    return {
        "list_http_status": list_status,
        "list_raw": data1,
        "details": details
    }

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

def extract_order_time(d):
    """
    Lấy thời gian đặt hàng từ:
    1. Timeline sự kiện đầu tiên (oldest event)
    2. Field create_time, ctime, order_time
    3. Fallback: thời gian hiện tại
    """
    # Thử lấy từ các field trực tiếp
    for key in ["create_time", "ctime", "order_time", "order_create_time", "purchase_time", "placed_time"]:
        val = find_first_key(d, key)
        if val is not None:
            # Convert timestamp sang string
            if isinstance(val, str) and val.isdigit():
                val = int(val)
            
            if isinstance(val, (int, float)):
                try:
                    # Thử timestamp giây
                    if 1000000000 < val < 9999999999:
                        dt = datetime.fromtimestamp(int(val))
                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                    # Thử timestamp milliseconds
                    elif 1000000000000 < val < 9999999999999:
                        dt = datetime.fromtimestamp(int(val) / 1000)
                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            
            # Nếu đã là string date
            if isinstance(val, str) and val.strip():
                return val.strip()
    
    # Lấy từ timeline (sự kiện cũ nhất = thời gian đặt hàng)
    _, full_timeline = build_rich_timeline(d)
    if full_timeline:
        # Timeline được sort theo thời gian mới nhất → lấy item cuối cùng
        oldest_event = full_timeline[-1] if full_timeline else None
        if oldest_event and oldest_event[0]:
            # oldest_event = (time_str, description)
            return oldest_event[0]
    
    # Fallback: không có data
    return None

def extract_order_code(d, fallback: Optional[str] = None) -> Optional[str]:
    """
    Ưu tiên các key mã đơn thường gặp của Shopee.
    Nếu không có thì fallback về order_id lấy từ API list.
    """
    key_list = (
        "order_sn", "orderSn",
        "order_id", "orderId",
        "order_code", "orderCode",
        "order_no", "orderNo",
        "ordersn", "orderid", "orderno", "ordercode",
    )

    for k in key_list:
        v = find_first_key(d, k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s

    if fallback is not None:
        s = str(fallback).strip()
        if s:
            return s
    return None

def pick_columns_from_detail(detail_raw: dict, fallback_order_id: Optional[str] = None) -> dict:
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

    # ✅ THÊM: Thời gian đặt hàng
    s["order_time"] = extract_order_time(d)
    s["order_code"] = extract_order_code(d, fallback=fallback_order_id)

    return s

def fetch_shopee_account_info(cookie: str, timeout: int = 10):
    headers = build_headers(cookie)
    status, raw = http_get(CHECK_URL, headers, timeout=timeout)

    err_code = None
    if isinstance(raw, dict):
        err_code = raw.get("error")
    live = status == 200 and err_code in (None, 0, "0", "")

    username = find_first_key(raw, "username") if isinstance(raw, dict) else None
    user_id = find_first_key(raw, "userid") if isinstance(raw, dict) else None
    if user_id is None and isinstance(raw, dict):
        user_id = find_first_key(raw, "user_id")
    phone = find_first_key(raw, "phone") if isinstance(raw, dict) else None
    email = find_first_key(raw, "email") if isinstance(raw, dict) else None
    display_name = (
        find_first_key(raw, "display_name") if isinstance(raw, dict) else None
    ) or (find_first_key(raw, "name") if isinstance(raw, dict) else None)

    return {
        "live": bool(live),
        "http_status": status,
        "error": (raw.get("error_msg") if isinstance(raw, dict) else "") or "",
        "raw": raw if isinstance(raw, dict) else {"raw": str(raw)},
        "user": {
            "username": username,
            "user_id": user_id,
            "phone": phone,
            "email": email,
            "display_name": display_name,
        },
    }

def parse_cookie_inputs(payload: dict):
    lines = []

    cookies = payload.get("cookies")
    if isinstance(cookies, list):
        for ck in cookies:
            if isinstance(ck, str) and ck.strip():
                lines.append(ck.strip())

    cookies_text = payload.get("cookies_text")
    if isinstance(cookies_text, str) and cookies_text.strip():
        for ln in cookies_text.replace("\r", "\n").split("\n"):
            if ln.strip():
                lines.append(ln.strip())

    one_cookie = payload.get("cookie")
    if isinstance(one_cookie, str) and one_cookie.strip():
        lines.append(one_cookie.strip())

    out, seen = [], set()
    for ln in lines:
        ck = sanitize_cookie(ln)
        if not ck:
            continue
        if ck in seen:
            continue
        seen.add(ck)
        out.append(ck)
    return out

def fetch_order_ids_with_meta(cookie: str, limit: int = 6, offset: int = 0, timeout: int = 12):
    list_url = f"{BASE}/order/get_all_order_and_checkout_list"
    variants = build_order_header_variants(cookie)
    last_status, last_data = 0, {}

    for headers in variants:
        status, data = http_get(
            list_url,
            headers,
            params={"limit": int(limit), "offset": int(offset)},
            timeout=timeout,
        )
        last_status, last_data = status, data
        if status != 200 or not isinstance(data, dict):
            continue

        ids = bfs_values_by_key(data, ("order_id",))
        uniq, seen = [], set()
        for oid in ids:
            s = str(oid).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            uniq.append(s)

        if uniq:
            return uniq, {"status_code": status, "error": ""}

    err = ""
    if isinstance(last_data, dict):
        emsg = str(last_data.get("message") or last_data.get("error_msg") or "").strip()
        ecode = last_data.get("error")
        if last_status and last_status != 200:
            err = f"HTTP {last_status}"
        if ecode not in (None, "", 0, "0"):
            err = (err + " - " if err else "") + f"error {ecode}"
        if emsg:
            err = (err + " - " if err else "") + emsg
    if not err:
        err = f"HTTP {last_status or 0}"
    return [], {"status_code": last_status, "error": err}

def fetch_order_detail_by_id(cookie: str, order_id: str, timeout: int = 12):
    detail_url = f"{BASE}/order/get_order_detail"
    variants = build_order_header_variants(cookie)
    last_status, last_data = 0, {}

    for headers in variants:
        status, data = http_get(
            detail_url,
            headers,
            params={"order_id": str(order_id)},
            timeout=timeout,
        )
        last_status, last_data = status, data
        if status == 200 and isinstance(data, dict):
            return data, {"status_code": status, "error": ""}

    err = ""
    if isinstance(last_data, dict):
        emsg = str(last_data.get("message") or last_data.get("error_msg") or "").strip()
        ecode = last_data.get("error")
        if last_status and last_status != 200:
            err = f"HTTP {last_status}"
        if ecode not in (None, "", 0, "0"):
            err = (err + " - " if err else "") + f"error {ecode}"
        if emsg:
            err = (err + " - " if err else "") + emsg
    if not err:
        err = f"HTTP {last_status or 0}"
    return (last_data if isinstance(last_data, dict) else {}), {"status_code": last_status, "error": err}

def is_delivered_status_text(status: str) -> bool:
    s = normalize_status_text(status).lower()
    if not s:
        return False
    bad = ("hủy", "huỷ", "cancel", "thất bại", "failed", "return", "refund")
    if any(k in s for k in bad):
        return False
    return (
        "giao hàng thành công" in s
        or "giao hang thanh cong" in s
        or "đã giao" in s
        or "da giao" in s
        or "delivered" in s
    )

def is_detail_delivered(detail_raw: dict) -> bool:
    s = pick_columns_from_detail(detail_raw).get("status_text") or ""
    if is_delivered_status_text(str(s)):
        return True
    return tree_contains_str(detail_raw, "label_order_delivered") or tree_contains_str(
        detail_raw, "order_status_text_to_receive_delivery_done"
    )

def _confirm_error_is_already_done(raw_error_text: str, api_data=None) -> bool:
    combined = []
    if raw_error_text:
        combined.append(str(raw_error_text))
    if isinstance(api_data, dict):
        for key in ("error_msg", "message", "msg", "error"):
            val = str(api_data.get(key) or "").strip()
            if val:
                combined.append(val)
        data_obj = api_data.get("data")
        if isinstance(data_obj, dict):
            if bool(data_obj.get("is_confirmed")):
                return True
            for key in ("message", "status_text", "status"):
                val = str(data_obj.get(key) or "").strip()
                if val:
                    combined.append(val)
    norm = " | ".join(combined).lower()
    if "kindnotsupported" in norm and "categorydataorderinfo" in norm:
        return True
    if "is_confirmed" in norm:
        return True
    if "already" in norm and "confirm" in norm:
        return True
    if "đã xác nhận" in norm or "da xac nhan" in norm:
        return True
    return False

def _humanize_confirm_error(raw_error_text: str, api_data=None) -> str:
    text = str(raw_error_text or "").strip()
    if not text and isinstance(api_data, dict):
        text = str(
            api_data.get("error_msg")
            or api_data.get("message")
            or api_data.get("msg")
            or api_data.get("error")
            or ""
        ).strip()
    norm = text.lower()
    if _confirm_error_is_already_done(raw_error_text, api_data):
        return "Don da xac nhan truoc do."
    if "http 401" in norm:
        return "Cookie het han hoac khong hop le (401)."
    if "http 403" in norm:
        return "Shopee tu choi yeu cau (403)."
    if "http 429" in norm:
        return "Bi gioi han tan suat (429), thu lai sau."
    if not text:
        return "Xac nhan don that bai."
    return text[:220]

def request_buyer_confirm_order(order_id: str, cookie_text: str):
    order_id_val = str(order_id or "").strip()
    cookie_val = sanitize_cookie(str(cookie_text or "").strip())
    if not order_id_val:
        return False, {}, "Thieu order_id."
    if not cookie_val:
        return False, {}, "Thieu cookie."

    ckm = cookie_map(cookie_val)
    csrf_val = str(ckm.get("csrftoken") or ckm.get("CSRFTOKEN") or "").strip()

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://shopee.vn",
        "Referer": "https://shopee.vn/user/purchase/?type=8",
        "User-Agent": SHOPEE_CONFIRM_UA,
        "X-API-SOURCE": "pc",
        "X-Requested-With": "XMLHttpRequest",
        "X-Shopee-Language": "vi",
        "x-shopee-language": "vi",
        "Cookie": cookie_val,
    }
    if csrf_val:
        headers["X-CSRFToken"] = csrf_val
        headers["x-csrftoken"] = csrf_val

    payload = {"order_id": int(order_id_val) if str(order_id_val).isdigit() else order_id_val}
    status, body = http_post(SHOPEE_CONFIRM_URL, headers, payload=payload, timeout=15)

    if status != 200:
        msg = ""
        if isinstance(body, dict):
            msg = str(
                body.get("message")
                or body.get("msg")
                or body.get("error_msg")
                or body.get("error")
                or ""
            ).strip()
        if not msg:
            msg = f"HTTP {status or 0}"
        return False, (body if isinstance(body, dict) else {}), msg

    if not isinstance(body, dict):
        return False, {}, "API confirm khong tra JSON hop le."

    if body.get("ok") is False:
        return False, body, str(body.get("error") or body.get("message") or "Xac nhan that bai.")

    err = body.get("error")
    if err not in (None, 0, "0", "", False):
        msg = str(body.get("error_msg") or body.get("message") or err).strip()
        return False, body, msg or "Xac nhan that bai."

    msg = str(body.get("message") or body.get("msg") or "").strip()
    if msg:
        msg_norm = msg.lower()
        if any(k in msg_norm for k in ("that bai", "khong", "loi", "error", "fail")):
            return False, body, msg

    return True, body, ""

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
    cookie = sanitize_cookie(cookie)

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

    account_meta = fetch_shopee_account_info(cookie, timeout=10)
    fetched = fetch_orders_and_details(cookie, list_limit=list_limit, offset=0)
    details = fetched.get("details", []) if isinstance(fetched, dict) else []
    shopee_full = {
        "list_http_status": fetched.get("list_http_status") if isinstance(fetched, dict) else None,
        "list_raw": fetched.get("list_raw") if isinstance(fetched, dict) else None,
        "details_raw": [],
        "account_http_status": account_meta.get("http_status"),
        "account_raw": account_meta.get("raw"),
    }

    picked = []
    for det in details:
        raw = det.get("raw") or {}
        # skip đơn bị buyer hủy
        if is_buyer_cancelled(raw):
            continue

        s = pick_columns_from_detail(raw, fallback_order_id=det.get("order_id"))
        s["order_id"] = str(det.get("order_id")) if det.get("order_id") is not None else None
        s["shopee_raw"] = raw

        shopee_full["details_raw"].append({
            "order_id": det.get("order_id"),
            "http_status": det.get("http_status"),
            "raw": raw
        })

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
            "message": "Cookie khóa/hết hạn hoặc không có đơn hợp lệ",
            "user_shopee": account_meta.get("user"),
            "cookie_live": bool(account_meta.get("live")),
            "shopee_full": shopee_full
        })

    return jsonify({
        "data": picked[0],
        "data_list": picked,
        "count": len(picked),
        "user_shopee": account_meta.get("user"),
        "cookie_live": bool(account_meta.get("live")),
        "shopee_full": shopee_full
    })

@app.post("/api/confirm-order")
def api_confirm_order():
    data = request.get_json(silent=True) or {}
    cookie = sanitize_cookie(str(data.get("cookie") or "").strip())
    order_id = str(data.get("order_id") or "").strip()

    if not cookie:
        return jsonify({"ok": False, "error": "Missing cookie"}), 400
    if not order_id:
        return jsonify({"ok": False, "error": "Missing order_id"}), 400

    ok_confirm, confirm_data, confirm_err = request_buyer_confirm_order(order_id, cookie)
    if ok_confirm:
        return jsonify({
            "ok": True,
            "state": "success",
            "message": "Xac nhan thanh cong",
            "order_id": order_id,
            "api_data": confirm_data if isinstance(confirm_data, dict) else {},
        })

    if _confirm_error_is_already_done(confirm_err, confirm_data):
        return jsonify({
            "ok": True,
            "state": "already",
            "message": "Don da xac nhan truoc do",
            "order_id": order_id,
            "api_data": confirm_data if isinstance(confirm_data, dict) else {},
        })

    return jsonify({
        "ok": False,
        "state": "failed",
        "message": _humanize_confirm_error(confirm_err, confirm_data),
        "order_id": order_id,
        "api_data": confirm_data if isinstance(confirm_data, dict) else {},
    }), 400

@app.post("/api/confirm-received-sll")
def api_confirm_received_sll():
    payload = request.get_json(silent=True) or {}
    started = time.time()

    order_limit = payload.get("order_limit", 6)
    max_cookies = payload.get("max_cookies", 50)
    try:
        order_limit = max(1, min(int(order_limit), 12))
    except Exception:
        order_limit = 6
    try:
        max_cookies = max(1, min(int(max_cookies), 200))
    except Exception:
        max_cookies = 50

    cookies_all = parse_cookie_inputs(payload)
    input_count = len(cookies_all)
    cookies = cookies_all[:max_cookies]
    truncated_count = max(0, len(cookies_all) - len(cookies))

    cookie_rows = []
    order_rows = []

    for ck in cookies:
        row = {
            "cookie": ck,
            "cookie_preview": (ck[:56] + "...") if len(ck) > 56 else ck,
            "live": False,
            "delivered_count": 0,
            "confirmed_count": 0,
            "already_count": 0,
            "failed_count": 0,
            "note": "",
            "order_api_error": "",
        }

        ids, meta = fetch_order_ids_with_meta(ck, limit=order_limit, offset=0, timeout=12)
        row["order_api_error"] = str((meta or {}).get("error") or "").strip()
        if not ids:
            live_meta = fetch_shopee_account_info(ck, timeout=8)
            row["live"] = bool(live_meta.get("live"))
            if row["live"]:
                row["note"] = row["order_api_error"] or "Khong co don gan day."
            else:
                row["note"] = str(live_meta.get("error") or "").strip() or "Cookie die/het han."
            cookie_rows.append(row)
            continue

        row["live"] = True
        seen_oid = set()
        for oid in ids[:order_limit]:
            oid = str(oid or "").strip()
            if not oid or oid in seen_oid:
                continue
            seen_oid.add(oid)

            detail, _detail_meta = fetch_order_detail_by_id(ck, oid, timeout=12)
            if not isinstance(detail, dict) or not detail:
                continue
            if not is_detail_delivered(detail):
                continue

            row["delivered_count"] += 1
            summary = pick_columns_from_detail(detail, fallback_order_id=oid)
            tracking_no = summary.get("tracking_no")
            status_text = summary.get("status_text") or "—"

            ok_confirm, confirm_data, confirm_err = request_buyer_confirm_order(oid, ck)
            confirm_state = "success"
            result_text = "✅ Thanh cong"
            if not ok_confirm:
                if _confirm_error_is_already_done(confirm_err, confirm_data):
                    ok_confirm = True
                    confirm_state = "already"
                    result_text = "ℹ️ Da xac nhan truoc do"
                else:
                    confirm_state = "failed"
                    result_text = f"❌ {_humanize_confirm_error(confirm_err, confirm_data)}"

            if ok_confirm:
                row["confirmed_count"] += 1
                if confirm_state == "already":
                    row["already_count"] += 1
            else:
                row["failed_count"] += 1

            order_rows.append({
                "cookie_preview": row["cookie_preview"],
                "order_id": oid,
                "tracking_no": tracking_no,
                "status_text": status_text,
                "ok": bool(ok_confirm),
                "state": confirm_state,
                "result_text": result_text,
                "api_data": confirm_data if isinstance(confirm_data, dict) else {},
            })

        if row["delivered_count"] <= 0:
            row["note"] = "Khong co don GTC de xac nhan."
        elif row["failed_count"] > 0:
            row["note"] = f"Xac nhan {row['confirmed_count']}/{row['delivered_count']} don."
        elif row["already_count"] > 0:
            row["note"] = f"Da xac nhan/da co san {row['confirmed_count']} don."
        else:
            row["note"] = f"Da xac nhan {row['confirmed_count']} don."
        cookie_rows.append(row)

    for idx, row in enumerate(cookie_rows, start=1):
        row["index"] = idx
    for idx, row in enumerate(order_rows, start=1):
        row["index"] = idx

    live_count = sum(1 for r in cookie_rows if bool(r.get("live")))
    delivered_count = sum(max(0, int(r.get("delivered_count") or 0)) for r in cookie_rows)
    confirmed_count = sum(max(0, int(r.get("confirmed_count") or 0)) for r in cookie_rows)
    already_count = sum(max(0, int(r.get("already_count") or 0)) for r in cookie_rows)
    failed_count = sum(max(0, int(r.get("failed_count") or 0)) for r in cookie_rows)

    return jsonify({
        "ok": True,
        "cookie_rows": cookie_rows,
        "order_rows": order_rows,
        "input_count": int(input_count),
        "total": len(cookie_rows),
        "live_count": int(live_count),
        "die_count": int(len(cookie_rows) - live_count),
        "delivered_count": int(delivered_count),
        "confirmed_count": int(confirmed_count),
        "already_count": int(already_count),
        "failed_count": int(failed_count),
        "elapsed": round(max(0.0, time.time() - started), 3),
        "truncated_count": int(truncated_count),
        "order_limit": int(order_limit),
    })

# Vercel needs "app" exported
# (this file is used as api/index.py)
