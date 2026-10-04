"""flight-cancel-subscription (POST /cancel) - stop renewals via ECPay CreditCardPeriodAction (Action=Cancel).
active -> cancelled (grace: keeps current_period_end, still alerted until then) + {event_type: "cancel"}.
pending_payment (never paid) -> expired. Already cancelled/expired -> no-op.
"""
# Built from m2/src/common.py + m2/src/cancel_subscription.py (single-file index.handler)
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

import time
from botocore.exceptions import ClientError

TABLE = boto3.resource("dynamodb").Table("subscriptions")
_sqs = boto3.client("sqs")
STATUS_QUEUE = os.environ.get("STATUS_QUEUE_NAME", "flight-status-queue")


def _qurl():
    if "qurl" not in _cache:
        _cache["qurl"] = _sqs.get_queue_url(QueueName=STATUS_QUEUE)["QueueUrl"]
    return _cache["qurl"]


def ecpay_cancel(cfg, mtn):
    params = {"MerchantID": cfg["merchant_id"], "MerchantTradeNo": mtn, "Action": "Cancel",
              "TimeStamp": str(int(time.time()))}
    params["CheckMacValue"] = gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])
    req = urllib.request.Request("https://%s/Cashier/CreditCardPeriodAction" % ecpay_host(cfg),
                                 data=urllib.parse.urlencode(params).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        body = "HTTP %s %s" % (ex.code, ex.read().decode("utf-8", "replace")[:300])
    except (urllib.error.URLError, TimeoutError) as ex:
        body = "network error %s" % ex
    res = {k: v[0] for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items()}
    return res.get("RtnCode"), res.get("RtnMsg") or body[:300]


def handler(event, context):
    try:
        email = caller_email(event)
        data = http_body(event)
    except AuthError as ex:
        return resp_json(401, {"error": "請先登入 / sign in required", "detail": str(ex)})
    except (ValueError, TypeError):
        return resp_json(400, {"error": "invalid JSON body"})
    route = str(data.get("route", "")).strip().upper()
    if route not in ROUTE_LABEL:
        return resp_json(400, {"error": "unknown route"})
    key = {"email": email, "route": route}
    item = TABLE.get_item(Key=key).get("Item")
    if not item:
        return resp_json(404, {"error": "subscription not found"})
    status = item.get("subscription_status")
    now = utcnow()

    if status in ("cancelled", "expired"):
        return resp_json(200, {"ok": True, "unchanged": True, "subscription": to_json(item)})

    cfg = ecpay_cfg()
    code, msg = (None, "no merchant_trade_no")
    if item.get("merchant_trade_no"):
        code, msg = ecpay_cancel(cfg, item["merchant_trade_no"])
    # 90100150 (unknown order) on a never-paid / synthetic order is expected: log it and still cancel locally
    print("CreditCardPeriodAction Cancel", key, item.get("merchant_trade_no"), "->", code, msg)

    if status != "active":  # pending_payment or legacy M1 row: nothing was paid, so no grace period
        out = TABLE.update_item(Key=key, UpdateExpression="SET subscription_status=:x, cancelled_at=:n, updated_at=:n",
                                ExpressionAttributeValues={":x": "expired", ":n": ts(now)}, ReturnValues="ALL_NEW")
        return resp_json(200, {"ok": True, "subscription": to_json(out["Attributes"]), "ecpay": {"code": code, "msg": msg}})

    end = item.get("current_period_end") or ts(add_period(now, "M", 1))  # migration fallback
    try:
        out = TABLE.update_item(
            Key=key,
            UpdateExpression=("SET subscription_status=:c, current_period_end=:e, current_period_end_date=:ed, "
                              "cancelled_at=:n, ecpay_cancel_rtn=:r, updated_at=:n"),
            ConditionExpression="subscription_status = :a",
            ExpressionAttributeValues={":c": "cancelled", ":e": end, ":ed": tpe_date(end), ":n": ts(now),
                                       ":r": "%s %s" % (code, msg), ":a": "active"},
            ReturnValues="ALL_NEW")["Attributes"]
    except ClientError as ex:
        if ex.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return resp_json(200, {"ok": True, "unchanged": True})
    print("CANCELLED (grace until %s)" % end, key)
    _sqs.send_message(QueueUrl=_qurl(), MessageBody=json.dumps({
        "event_type": "cancel", "email": email, "route": route, "merchant_trade_no": item.get("merchant_trade_no", ""),
        "target_price": int(item.get("target_price", 0)), "current_period_end": end}, ensure_ascii=False))
    return resp_json(200, {"ok": True, "subscription": to_json(out), "ecpay": {"code": code, "msg": msg}})
