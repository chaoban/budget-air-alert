"""flight-save-subscription (POST /subscribe) - M2.

- active, or cancelled but still inside the paid period -> update target_price in place, JSON response.
- anything else (new / pending_payment / expired / legacy M1 row) -> subscription_status = pending_payment,
  new MerchantTradeNo, and an ECPay 信用卡定期定額 auto-submit form (text/html) the browser posts to the cashier.
Callbacks (flight-ecpay-return / -period) are the only writers of `active`.
"""
# Built from m2/src/common.py + m2/src/save_subscription.py (single-file index.handler)
# ===== shared helpers (folded into every M2 Lambda at build time; stdlib + boto3 only) =====
import base64
import calendar
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
TPE_TZ = timezone(timedelta(hours=8))
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"  # the ONE timestamp format for current_period_end (compared as strings)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLANS = {"tokyo": {"origin": "TPE", "destination": "TYO", "label": "台北 → 東京"},
         "seoul": {"origin": "TPE", "destination": "SEL", "label": "台北 → 首爾"},
         "london": {"origin": "TPE", "destination": "LON", "label": "台北 → 倫敦"}}
ROUTE_LABEL = {p["origin"] + "-" + p["destination"]: p["label"] for p in PLANS.values()}

_sm = boto3.client("secretsmanager")
_cache = {}


def secret(name):
    if name not in _cache:
        _cache[name] = json.loads(_sm.get_secret_value(SecretId=name)["SecretString"])
    return _cache[name]


def ecpay_cfg():
    return secret("flight/ecpay")


def ecpay_host(cfg):
    return "payment.ecpay.com.tw" if cfg.get("env") == "prod" else "payment-stage.ecpay.com.tw"


# ---------- time ----------
def utcnow():
    return datetime.now(timezone.utc)


def ts(dt):
    return dt.astimezone(timezone.utc).strftime(TS_FMT)


def parse_ts(s):
    return datetime.strptime(s, TS_FMT).replace(tzinfo=timezone.utc)


def add_period(dt, period_type="M", frequency=1):
    if period_type == "D":
        return dt + timedelta(days=frequency)
    months = frequency * (12 if period_type == "Y" else 1)
    y, m = divmod(dt.month - 1 + months, 12)
    y, m = dt.year + y, m + 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def period_end(base, period_type="M", frequency=1):
    """Paid-through moment: the Taipei calendar date one period after `base`, through 23:59:59 that day (UTC dt).
    Calendar math runs on the Taipei date, so a 1/31 payment ends 2/28 23:59:59 (Taipei), never 3/1."""
    local = add_period(base.astimezone(TPE_TZ), period_type, frequency)
    return local.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(timezone.utc)


def tpe_date(ts_str):
    return parse_ts(ts_str).astimezone(TPE_TZ).strftime("%Y/%m/%d")


# ---------- ECPay CheckMacValue (ecpay-best-practice Rule 2; passes ecpay/test-vectors) ----------
def ecpay_url_encode(s):
    e = urllib.parse.quote_plus(str(s)).replace("~", "%7E").lower()
    for o, n in (("%2d", "-"), ("%5f", "_"), ("%2e", "."), ("%21", "!"),
                 ("%2a", "*"), ("%28", "("), ("%29", ")")):
        e = e.replace(o, n)
    return e


def gen_cmv(params, hash_key, hash_iv):
    items = {k: v for k, v in params.items() if k != "CheckMacValue"}  # KEEP empty-string values
    body = "&".join("%s=%s" % (k, items[k]) for k in sorted(items, key=str.lower))
    raw = "HashKey=%s&%s&HashIV=%s" % (hash_key, body, hash_iv)
    return hashlib.sha256(ecpay_url_encode(raw).encode("utf-8")).hexdigest().upper()


def verify_cmv(params, cfg):
    return params.get("CheckMacValue", "").upper() == gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])


def form_params(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}


# ---------- HTTP responses ----------
def resp_json(code, obj):
    return {"statusCode": code, "headers": {"content-type": "application/json"},
            "body": json.dumps(obj, ensure_ascii=False, default=_dec)}


def resp_text(body, code=200):
    return {"statusCode": code, "headers": {"Content-Type": "text/plain; charset=utf-8"}, "body": body}


def _dec(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def to_json(item):
    return json.loads(json.dumps(item, default=_dec))


# ---------- auth: the caller's email comes from a verified Supabase session ----------
class AuthError(Exception):
    pass


def caller_email(event):
    """HTTP (API Gateway) calls must carry `Authorization: Bearer <Supabase access token>`; the email
    is read from Supabase, never from the request body (ecpay-best-practice Rule 5).
    Direct Lambda invokes (no requestContext - only IAM principals can do that) may pass `email`."""
    if "requestContext" not in event:
        email = str(event.get("email") or json.loads(event.get("body") or "{}").get("email") or "")
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError("direct invoke needs an email")
        return email
    hdrs = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = hdrs.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    token = auth[7:].strip()
    hit = _cache.get("tok:" + token)
    if hit and hit[1] > utcnow():
        return hit[0]
    sb = secret("flight/supabase")
    req = urllib.request.Request(sb["url"].rstrip("/") + "/auth/v1/user",
                                 headers={"apikey": sb["publishable_key"], "Authorization": "Bearer " + token,
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            user = json.loads(r.read())
    except urllib.error.HTTPError as ex:
        raise AuthError("supabase rejected token (%s)" % ex.code)
    email = str(user.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("no email on user")
    _cache["tok:" + token] = (email, utcnow() + timedelta(minutes=5))
    return email


def http_body(event):
    raw = event.get("body")
    if raw is None:
        return event
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw or "{}")
# ===== end shared helpers =====

import html
import secrets
import string

TABLE = boto3.resource("dynamodb").Table("subscriptions")
API_BASE = os.environ.get("API_BASE_URL", "").strip().rstrip("/")
SITE_URL = os.environ.get("SITE_URL", "https://budget-air-alert.vercel.app").strip().rstrip("/")
PERIOD_TYPE = os.environ.get("PERIOD_TYPE", "M").strip()          # D only for the renewal test
FREQUENCY = int(os.environ.get("FREQUENCY", "1"))
EXEC_TIMES = int(os.environ.get("EXEC_TIMES", "999"))
ALNUM = string.ascii_uppercase + string.digits


def _trade_no():
    # <= 20 chars, alphanumeric, unique: FP + yymmddHHMMSS + 6 random
    return "FP" + datetime.now(TPE_TZ).strftime("%y%m%d%H%M%S") + "".join(secrets.choice(ALNUM) for _ in range(6))


def _in_grace(item, now_s):
    return item.get("subscription_status") == "cancelled" and str(item.get("current_period_end", "")) >= now_s


def checkout_form(cfg, mtn, email, route, plan_name):
    amount = str(int(Decimal(str(cfg["amount"]))))
    params = {
        "MerchantID": cfg["merchant_id"], "MerchantTradeNo": mtn,
        "MerchantTradeDate": datetime.now(TPE_TZ).strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio", "ChoosePayment": "Credit", "EncryptType": "1",
        "TotalAmount": amount, "PeriodAmount": amount,
        "PeriodType": PERIOD_TYPE, "Frequency": str(FREQUENCY), "ExecTimes": str(EXEC_TIMES),
        "TradeDesc": "Flight Price Notifier monthly plan",
        "ItemName": "Flight Price Notifier %s monthly plan" % route,
        "ReturnURL": API_BASE + "/ecpay-return",
        "PeriodReturnURL": API_BASE + "/ecpay-period",
        "OrderResultURL": API_BASE + "/ecpay-result",
        "ClientBackURL": SITE_URL + "/app",
        "CustomField1": email, "CustomField2": route, "CustomField3": plan_name,
    }
    params["CheckMacValue"] = gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])
    action = "https://%s/Cashier/AioCheckOut/V5" % ecpay_host(cfg)
    inputs = "\n".join('<input type="hidden" name="%s" value="%s">' % (html.escape(k), html.escape(str(v)))
                       for k, v in params.items())
    return ('<!doctype html><html><head><meta charset="utf-8"><title>前往綠界付款…</title></head>'
            '<body><p style="font-family:sans-serif">正在前往綠界付款頁面…</p>'
            '<form id="ecpay" action="%s" method="post">\n%s\n</form>'
            '<script>document.forms[0].submit()</script></body></html>') % (html.escape(action), inputs)


def handler(event, context):
    try:
        email = caller_email(event)
    except AuthError as ex:
        return resp_json(401, {"error": "請先登入 / sign in required", "detail": str(ex)})
    try:
        data = http_body(event)
    except (ValueError, TypeError):
        return resp_json(400, {"error": "invalid JSON body"})

    plan_name = str(data.get("plan_name", "")).strip().lower()
    if plan_name not in PLANS:
        return resp_json(400, {"error": "plan_name must be one of " + ", ".join(PLANS)})
    try:
        tp = Decimal(str(data.get("target_price"))).to_integral_value()
        if not tp.is_finite() or tp <= 0 or tp > 1000000:
            raise ValueError
    except Exception:
        return resp_json(400, {"error": "target_price must be between 1 and 1,000,000 TWD"})

    plan = PLANS[plan_name]
    route = plan["origin"] + "-" + plan["destination"]
    now_s = ts(utcnow())
    key = {"email": email, "route": route}
    item = TABLE.get_item(Key=key).get("Item") or {}
    status = item.get("subscription_status")

    if status == "active" or _in_grace(item, now_s):
        # paid (or paid-through) subscriber: change the target in place - no re-payment, status untouched
        out = TABLE.update_item(Key=key, UpdateExpression="SET target_price=:t, updated_at=:n",
                                ConditionExpression="subscription_status = :s",
                                ExpressionAttributeValues={":t": tp, ":n": now_s, ":s": status},
                                ReturnValues="ALL_NEW")["Attributes"]
        print("target updated in place", email, route, int(tp), "status", status)
        return resp_json(200, {"ok": True, "updated": True, "subscription": to_json(out)})

    cfg = ecpay_cfg()
    mtn = _trade_no()
    TABLE.update_item(
        Key=key,
        UpdateExpression=("SET plan_name=:p, origin=:o, destination=:d, target_price=:t, currency=:c, "
                          "subscription_status=:s, merchant_trade_no=:m, period_type=:pt, period_frequency=:pf, "
                          "amount=:a, updated_at=:n, created_at=if_not_exists(created_at,:n)"),
        ExpressionAttributeValues={":p": plan_name, ":o": plan["origin"], ":d": plan["destination"], ":t": tp,
                                   ":c": "TWD", ":s": "pending_payment", ":m": mtn, ":pt": PERIOD_TYPE,
                                   ":pf": FREQUENCY, ":a": Decimal(str(cfg["amount"])), ":n": now_s})
    print("pending_payment", email, route, "target", int(tp), "MerchantTradeNo", mtn, "previous status", status)
    return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8"},
            "body": checkout_form(cfg, mtn, email, route, plan_name)}
