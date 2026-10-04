"""flight-cancel-subscription (POST /cancel) - stop renewals via ECPay CreditCardPeriodAction (Action=Cancel).
active -> cancelled (grace: keeps current_period_end, still alerted until then) + {event_type: "cancel"}.
pending_payment (never paid) -> expired. Already cancelled/expired -> no-op.
"""
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

    end = item.get("current_period_end") or ts(period_end(now, "M", 1))  # migration fallback
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
