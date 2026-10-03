"""flight-fare-notification: SQS consumer for flight-fare-queue.

Per message: dedup against notification_history (BEFORE sending) -> render the alert
(NT$ headline + optional 約 US$ line + 「立即訂購」) -> POST to Resend -> on a real 2xx,
write the history row. Transient failures (429 / 5xx / network) are reported back to
SQS as batch-item failures (redelivered); permanent ones (other 4xx) are logged and dropped.
M1 has NO payment guard: no subscription_status check.
"""
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
CITY = {"TPE": "台北", "TYO": "東京", "SEL": "首爾", "LON": "倫敦"}
AIRLINE = {"GK": "捷星日本", "IT": "台灣虎航", "MM": "樂桃航空", "JX": "星宇航空", "CI": "中華航空",
           "BR": "長榮航空", "JL": "日本航空", "NH": "全日空", "ZE": "易斯達航空", "7C": "濟州航空",
           "TW": "德威航空", "LJ": "真航空", "KE": "大韓航空", "OZ": "韓亞航空", "TR": "酷航",
           "CX": "國泰航空", "TK": "土耳其航空", "EK": "阿聯酋航空", "QR": "卡達航空", "EY": "阿提哈德航空",
           "SQ": "新加坡航空", "TG": "泰國航空", "VN": "越南航空", "MH": "馬來西亞航空", "KL": "荷蘭皇家航空",
           "LH": "漢莎航空", "BA": "英國航空", "AF": "法國航空", "AY": "芬蘭航空", "ET": "衣索比亞航空",
           "CA": "中國國際航空", "MU": "東方航空", "CZ": "南方航空", "HU": "海南航空", "ZH": "深圳航空",
           "MF": "廈門航空", "3U": "四川航空", "FM": "上海航空", "HX": "香港航空", "UO": "香港快運"}
SITE_URL = os.environ.get("SITE_URL", "https://budget-air-alert.vercel.app/app")
LOCK_SK = "#lock"  # per-(email, route) claim row in notification_history; real rows start with "20.."
LOCK_SECONDS = 120

_sm = boto3.client("secretsmanager")
_history = boto3.resource("dynamodb").Table("notification_history")
_cache = {}


class Transient(Exception):
    pass


def _resend():
    if "resend" not in _cache:
        _cache["resend"] = json.loads(_sm.get_secret_value(SecretId="flight/resend")["SecretString"])
    return _cache["resend"]


def _knob(name, default):
    return Decimal(os.environ.get(name, str(default)))


# ---------------------------------------------------------------- renderer (inline)

def _route(fare):
    o, d = fare["route"].split("-", 1)
    return o, d, CITY.get(o, o), CITY.get(d, d)


def _date(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _md(iso):
    dt = _date(iso)
    return "%d/%d" % (dt.month, dt.day) if dt else "—"


def booking_url(fare, marker=None, currency="twd"):
    """Aviasales deep link ORIGIN+DDMM+DEST+DDMM (return part only when present)."""
    o, d, _, _ = _route(fare)
    c = fare["cheapest"]
    dep, ret = _date(c.get("depart_date")), _date(c.get("return_date"))
    path = o + (dep.strftime("%d%m") if dep else "") + d + (ret.strftime("%d%m") if ret else "") + "1"
    q = {"currency": currency}
    if marker:
        q["marker"] = marker
    return "https://www.aviasales.com/search/%s?%s" % (path, urllib.parse.urlencode(q))


def subject(fare):
    _, _, oc, dc = _route(fare)
    return "✈️ %s → %s 降價通知！NT$%s 已達標" % (oc, dc, format(int(fare["cheapest"]["price"]), ","))


def _stops(c):
    n = c.get("transfers")
    if n is None:
        return ""
    return "直飛" if n == 0 else "轉機 %d 次" % n


def _airline(code):
    return "%s（%s）" % (AIRLINE[code], code) if code in AIRLINE else (code or "—")


def render_html(fare, target_price, marker=None, usd_price=None):
    o, d, oc, dc = _route(fare)
    c = fare["cheapest"]
    price = format(int(c["price"]), ",")
    usd = ('<p style="margin:4px 0 0;color:#6f5645;font-size:14px;">約 US$%s</p>' % format(int(usd_price), ",")
           if usd_price is not None else "")
    url = html.escape(booking_url(fare, marker))
    return (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,\'PingFang TC\',\'Microsoft JhengHei\','
        'sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#2a211b;line-height:1.6;">'
        '<p style="margin:0;color:#985d31;font-size:13px;">Flight Price Notifier · 機票降價通知</p>'
        '<h1 style="margin:8px 0 16px;font-size:20px;">%s → %s 已低於你的目標價</h1>'
        '<p style="margin:0;font-size:32px;font-weight:700;color:#bf4f1f;">NT$%s</p>%s'
        '<p style="margin:16px 0 0;font-size:14px;">你的目標價：NT$%s<br>'
        '航空公司：%s%s<br>出發 %s · 回程 %s（%s ⇄ %s 來回）</p>'
        '<p style="margin:24px 0;"><a href="%s" style="display:inline-block;background:#bf4f1f;color:#ffffff;'
        'text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:600;">立即訂購</a></p>'
        '<p style="margin:0;font-size:12px;color:#6f5645;">票價會隨時變動，以訂購頁面為準。'
        '你收到這封信是因為你在 Flight Price Notifier 追蹤了這條航線；'
        '<a href="%s" style="color:#985d31;">調整目標價</a>。</p></div>'
    ) % (oc, dc, price, usd, format(int(target_price), ","), html.escape(_airline(c.get("airline"))),
         (" · " + _stops(c)) if _stops(c) else "",
         _md(c.get("depart_date")), _md(c.get("return_date")), o, d, url, html.escape(SITE_URL))


def render_text(fare, target_price, marker=None, usd_price=None):
    o, d, oc, dc = _route(fare)
    c = fare["cheapest"]
    lines = ["%s → %s 已低於你的目標價" % (oc, dc), "",
             "最低來回票價：NT$%s" % format(int(c["price"]), ",")]
    if usd_price is not None:
        lines.append("約 US$%s" % format(int(usd_price), ","))
    lines += ["你的目標價：NT$%s" % format(int(target_price), ","),
              "航空公司：%s%s" % (_airline(c.get("airline")), (" · " + _stops(c)) if _stops(c) else ""),
              "出發 %s · 回程 %s（%s ⇄ %s 來回）" % (_md(c.get("depart_date")), _md(c.get("return_date")), o, d),
              "", "立即訂購：" + booking_url(fare, marker), "",
              "票價會隨時變動，以訂購頁面為準。調整目標價：" + SITE_URL]
    return "\n".join(lines)


# ---------------------------------------------------------------- dedup + send

def _claim(pk):
    """Atomically claim (email, route) so concurrent invocations can't both pass the dedup check."""
    now = int(time.time())
    try:
        _history.put_item(Item={"pk": pk, "sent_at": LOCK_SK, "lock_until": now + LOCK_SECONDS},
                          ConditionExpression="attribute_not_exists(pk) OR lock_until < :now",
                          ExpressionAttributeValues={":now": now})
        return True
    except ClientError as ex:
        if ex.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _release(pk):
    _history.update_item(Key={"pk": pk, "sent_at": LOCK_SK}, UpdateExpression="SET lock_until = :z",
                         ExpressionAttributeValues={":z": 0})


def _should_send(pk, new_price):
    q = _history.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sent_at").begins_with("2"),
                       ScanIndexForward=False, Limit=1)
    if not q.get("Items"):
        return True, "first alert"
    last = q["Items"][0]
    last_at = datetime.fromisoformat(last["sent_at"])
    if datetime.now(timezone.utc) - last_at >= timedelta(hours=float(_knob("NOTIFY_FLOOR_HOURS", 24))):
        return True, "floor elapsed since %s" % last["sent_at"]
    last_price = Decimal(str(last["price"]))
    if new_price <= last_price * (1 - _knob("REALERT_PCT", 20) / 100):
        return True, "dropped >= %s%% (last %s)" % (_knob("REALERT_PCT", 20), last_price)
    if last_price - new_price >= _knob("REALERT_ABS_TWD", 2000):
        return True, "dropped >= NT$%s (last %s)" % (_knob("REALERT_ABS_TWD", 2000), last_price)
    return False, "last alert %s at NT$%s" % (last["sent_at"], last_price)


def _post_resend(cfg, to, subj, html_body, text_body):
    body = {"from": cfg["from"], "to": [to], "subject": subj, "html": html_body, "text": text_body}
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


def process(msg):
    email, route = msg["email"], msg["route"]
    price = Decimal(str(msg["cheapest"]["price"]))
    pk = "%s#%s" % (email, route)
    if not _claim(pk):
        print("skipped (in-flight duplicate)", pk, "NT$%s" % price, "- another invocation holds the claim")
        return
    try:
        _deliver(msg, email, route, price, pk)
    finally:
        _release(pk)


def _deliver(msg, email, route, price, pk):
    ok, why = _should_send(pk, price)
    if not ok:
        print("skipped (deduped)", pk, "NT$%s" % price, "-", why)
        return
    usd = msg.get("cheapest_usd", {}).get("price") if msg.get("cheapest_usd") else None
    marker = _resend_marker()
    status, resp = _post_resend(_resend(), email, subject(msg),
                                render_html(msg, msg["target_price"], marker=marker, usd_price=usd),
                                render_text(msg, msg["target_price"], marker=marker, usd_price=usd))
    if 200 <= status < 300:
        _history.put_item(Item={"pk": pk, "sent_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                                "email": email, "route": route, "price": price, "currency": "TWD",
                                "target_price": Decimal(str(msg["target_price"])),
                                "resend_id": (resp or {}).get("id", "")})
        print("SENT", pk, "NT$%s" % price, "(%s)" % why, "resend", status, json.dumps(resp))
    elif status == 429 or status >= 500:
        raise Transient("resend %s %s" % (status, resp))
    else:
        print("DROPPED (permanent)", pk, "resend", status, resp)


def _resend_marker():
    return os.environ.get("TP_MARKER") or None


def handler(event, context):
    failures = []
    for rec in event.get("Records", []):
        try:
            process(json.loads(rec["body"]))
        except Transient as ex:
            print("RETRY", rec.get("messageId"), str(ex))
            failures.append({"itemIdentifier": rec["messageId"]})
        except (KeyError, ValueError, TypeError) as ex:
            print("DROPPED (bad message)", rec.get("messageId"), repr(ex), rec.get("body", "")[:300])
        time.sleep(0.25)  # stay well under Resend's 5 req/s
    return {"batchItemFailures": failures}
