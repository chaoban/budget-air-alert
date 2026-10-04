"""flight-status-notification - the ONE consumer of flight-status-queue, routed by event_type.
"welcome" (first payment activated) / "cancel" (renewals stopped, grace period). Sends via Resend.
Exactly-once per (event_type, email, route, MerchantTradeNo) via a conditional claim row in notification_history.
"""
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
