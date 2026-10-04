"""flight-ecpay-return (POST /ecpay-return) - ECPay ReturnURL, first period of 信用卡定期定額.
The source of truth for activation. Verify CMV -> (not SimulatePaid, RtnCode == "1") -> pending_payment -> active,
set current_period_end, enqueue {event_type: "welcome"}. Always answer the literal text 1|OK once handled.
"""
# Built from m2/src/common.py + m2/src/ecpay_return.py (single-file index.handler)
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

from botocore.exceptions import ClientError

TABLE = boto3.resource("dynamodb").Table("subscriptions")
_sqs = boto3.client("sqs")
STATUS_QUEUE = os.environ.get("STATUS_QUEUE_NAME", "flight-status-queue")


def _qurl():
    if "qurl" not in _cache:
        _cache["qurl"] = _sqs.get_queue_url(QueueName=STATUS_QUEUE)["QueueUrl"]
    return _cache["qurl"]


def handler(event, context):
    p = form_params(event)
    cfg = ecpay_cfg()
    safe = {k: v for k, v in p.items() if k not in ("CheckMacValue",)}
    print("ReturnURL callback", json.dumps(safe, ensure_ascii=False))
    if not verify_cmv(p, cfg):
        print("CheckMacValueInvalid received", p.get("CheckMacValue"), "expected", gen_cmv(p, cfg["hash_key"], cfg["hash_iv"]))
        return resp_text("0|CheckMacValueInvalid", 400)
    if p.get("MerchantID") != cfg["merchant_id"]:
        print("MerchantID mismatch", p.get("MerchantID"))
        return resp_text("0|MerchantIDMismatch", 400)
    if p.get("SimulatePaid") == "1":
        print("SimulatePaid=1 - CMV ok, acknowledged, NOT activating (ecpay-best-practice Rule 7)")
        return resp_text("1|OK")
    email, route, mtn = p.get("CustomField1", ""), p.get("CustomField2", ""), p.get("MerchantTradeNo", "")
    if p.get("RtnCode") != "1":
        print("first authorization failed - row stays pending_payment", email, route, mtn, p.get("RtnCode"), p.get("RtnMsg"))
        return resp_text("1|OK")
    if not (email and route and mtn):
        print("missing CustomField1/2 or MerchantTradeNo - cannot map to a subscription")
        return resp_text("1|OK")

    now = utcnow()
    item = TABLE.get_item(Key={"email": email, "route": route}).get("Item") or {}
    pt, freq = item.get("period_type", "M"), int(item.get("period_frequency", 1))
    end = ts(add_period(now, pt, freq))
    try:
        # idempotent on MerchantTradeNo: only the pending order that matches this trade-no is activated once
        TABLE.update_item(
            Key={"email": email, "route": route},
            UpdateExpression=("SET subscription_status=:a, current_period_end=:e, current_period_end_date=:ed, "
                              "activated_at=:n, last_charged_at=:n, total_success_times=:one, failed_attempts=:z, "
                              "ecpay_trade_no=:tn, updated_at=:n"),
            ConditionExpression="merchant_trade_no = :m AND subscription_status <> :a",
            ExpressionAttributeValues={":a": "active", ":e": end, ":ed": tpe_date(end), ":n": ts(now),
                                       ":one": 1, ":z": 0, ":tn": p.get("TradeNo", ""), ":m": mtn})
    except ClientError as ex:
        if ex.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        print("already processed or stale trade-no - no change", email, route, mtn,
              "row trade-no", item.get("merchant_trade_no"), "row status", item.get("subscription_status"))
        return resp_text("1|OK")
    print("ACTIVATED", email, route, mtn, "current_period_end", end)
    _sqs.send_message(QueueUrl=_qurl(), MessageBody=json.dumps({
        "event_type": "welcome", "email": email, "route": route, "merchant_trade_no": mtn,
        "target_price": int(item.get("target_price", 0)), "amount": int(Decimal(str(cfg["amount"]))),
        "current_period_end": end}, ensure_ascii=False))
    return resp_text("1|OK")
