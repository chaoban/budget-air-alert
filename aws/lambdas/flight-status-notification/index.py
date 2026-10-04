"""flight-status-notification - the ONE consumer of flight-status-queue, routed by event_type.
"welcome" (first payment activated) / "cancel" (renewals stopped, grace period). Sends via Resend.
Exactly-once per (event_type, email, route, MerchantTradeNo) via a conditional claim row in notification_history.
"""
# Built from m2/src/common.py + m2/src/status_notification.py (single-file index.handler)
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
import time
from botocore.exceptions import ClientError

HISTORY = boto3.resource("dynamodb").Table("notification_history")
SITE_URL = os.environ.get("SITE_URL", "https://budget-air-alert.vercel.app").strip().rstrip("/")
CLAIM_SECONDS = 120


class Transient(Exception):
    pass


def _claim(pk):
    now = int(time.time())
    try:
        HISTORY.put_item(Item={"pk": pk, "sent_at": "#once", "state": "sending", "claimed_until": now + CLAIM_SECONDS},
                         ConditionExpression="attribute_not_exists(pk) OR #s = :f OR (#s = :w AND claimed_until < :now)",
                         ExpressionAttributeNames={"#s": "state"},
                         ExpressionAttributeValues={":f": "failed", ":w": "sending", ":now": now})
        return True
    except ClientError as ex:
        if ex.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _mark(pk, state, extra=None):
    # every attribute goes through ExpressionAttributeNames: "state" and "error" are DynamoDB reserved words
    names, vals, sets = {"#s": "state", "#d": "done_at"}, {":s": state, ":n": ts(utcnow())}, ["#s = :s", "#d = :n"]
    for i, (k, v) in enumerate((extra or {}).items()):
        names["#x%d" % i], vals[":x%d" % i] = k, v
        sets.append("#x%d = :x%d" % (i, i))
    HISTORY.update_item(Key={"pk": pk, "sent_at": "#once"}, UpdateExpression="SET " + ", ".join(sets),
                        ExpressionAttributeNames=names, ExpressionAttributeValues=vals)


def _wrap(title, lines, button=None):
    body = "".join('<p style="margin:0 0 10px;font-size:15px;">%s</p>' % l for l in lines)
    btn = ('<p style="margin:22px 0;"><a href="%s" style="display:inline-block;background:#bf4f1f;color:#ffffff;'
           'text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:600;">%s</a></p>'
           % (html.escape(button[1]), html.escape(button[0]))) if button else ""
    return ('<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,\'PingFang TC\',\'Microsoft JhengHei\','
            'sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#2a211b;line-height:1.6;">'
            '<p style="margin:0;color:#985d31;font-size:13px;">Flight Price Notifier · 機票降價通知</p>'
            '<h1 style="margin:8px 0 16px;font-size:20px;">%s</h1>%s%s'
            '<p style="margin:0;font-size:12px;color:#6f5645;">這是交易通知信，訂閱與取消都可以在網站上管理。</p></div>'
            ) % (html.escape(title), body, btn)


def render(m):
    label = ROUTE_LABEL.get(m["route"], m["route"])
    end = tpe_date(m["current_period_end"]) if m.get("current_period_end") else "—"
    tp = format(int(m.get("target_price", 0)), ",")
    if m["event_type"] == "welcome":
        subject = "✅ 訂閱成功：%s 降價通知已啟用" % label
        lines = ["%s 的降價通知已經啟用。" % html.escape(label),
                 "目標價：NT$%s（下個月來回最低價小於或等於這個金額就寄信給你）" % tp,
                 "月費：NT$%s，綠界信用卡定期定額每月自動扣款" % format(int(m.get("amount", 0)), ","),
                 "本期有效至：%s" % end]
        text = "\n".join([label + " 的降價通知已經啟用。", "目標價：NT$" + tp,
                          "月費：NT$%s（每月自動扣款）" % format(int(m.get("amount", 0)), ","),
                          "本期有效至：" + end, "", "管理訂閱：" + SITE_URL + "/app"])
        return subject, _wrap("訂閱成功", lines, ("管理我的訂閱", SITE_URL + "/app")), text
    subject = "已取消訂閱：%s" % label
    lines = ["你已取消 %s 的降價通知訂閱，之後不會再自動扣款。" % html.escape(label),
             "本期已付費，降價通知會持續到 <b>%s</b>。" % end,
             "期間內仍可在網站上調整目標價；想繼續追蹤，到期後重新訂閱即可。"]
    text = "\n".join(["你已取消 %s 的降價通知訂閱，之後不會再自動扣款。" % label,
                      "本期已付費，降價通知會持續到 %s。" % end, "", "網站：" + SITE_URL + "/app"])
    return subject, _wrap("已取消訂閱", lines, ("回到網站", SITE_URL + "/app")), text


def send(to, subject, html_body, text):
    cfg = secret("flight/resend")
    body = {"from": cfg["from"], "to": [to], "subject": subject, "html": html_body, "text": text}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + cfg["api_key"],
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode()[:500]
    except (urllib.error.URLError, TimeoutError) as ex:
        raise Transient("network: %s" % ex)


def process(m):
    if m.get("event_type") not in ("welcome", "cancel"):
        print("DROPPED unknown event_type", m.get("event_type"))
        return
    pk = "status#%s#%s#%s#%s" % (m["event_type"], m["email"], m["route"], m.get("merchant_trade_no", ""))
    if not _claim(pk):
        print("skipped (already sent or in flight)", pk)
        return
    try:
        subject, h, t = render(m)
        status, resp = send(m["email"], subject, h, t)
    except Exception:
        _mark(pk, "failed")
        raise
    if 200 <= status < 300:
        _mark(pk, "sent", {"resend_id": (resp or {}).get("id", "")})
        print("SENT", m["event_type"], m["email"], m["route"], "resend", status, json.dumps(resp))
    elif status == 429 or status >= 500:
        _mark(pk, "failed")
        raise Transient("resend %s %s" % (status, resp))
    else:
        _mark(pk, "dropped", {"error": str(resp)[:300]})
        print("DROPPED (permanent)", pk, "resend", status, resp)


def handler(event, context):
    failures = []
    for rec in event.get("Records", []):
        try:
            process(json.loads(rec["body"]))
        except Transient as ex:
            print("RETRY", rec.get("messageId"), str(ex))
            failures.append({"itemIdentifier": rec["messageId"]})
        except (KeyError, ValueError, TypeError) as ex:
            print("DROPPED (bad message)", rec.get("messageId"), repr(ex))
        except Exception as ex:  # unexpected (e.g. DynamoDB): retry only this record, never the whole batch
            print("RETRY (error)", rec.get("messageId"), repr(ex))
            failures.append({"itemIdentifier": rec["messageId"]})
        time.sleep(0.25)
    return {"batchItemFailures": failures}
