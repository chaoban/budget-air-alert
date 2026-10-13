"""flight-ecpay-period (POST /ecpay-period) - ECPay PeriodReturnURL, 2nd charge onward.
Success -> extend current_period_end by one period (idempotent on TotalSuccessTimes).
Failure -> count it; ECPay retries and only terminates after 6 consecutive failures -> then expired.
Both outcomes enqueue an owner notice on flight-status-queue ({event_type: "renewed" | "renewal_failed"});
a queue error is logged and never fails the callback (bookkeeping first, notice best-effort).
"""
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

TABLE = boto3.resource("dynamodb").Table("subscriptions")
MAX_FAILS = 6
_sqs = boto3.client("sqs")
STATUS_QUEUE = os.environ.get("STATUS_QUEUE_NAME", "flight-status-queue")


def notify(msg):
    try:
        if "qurl" not in _cache:
            _cache["qurl"] = _sqs.get_queue_url(QueueName=STATUS_QUEUE)["QueueUrl"]
        _sqs.send_message(QueueUrl=_cache["qurl"], MessageBody=json.dumps(msg, ensure_ascii=False))
    except Exception as ex:  # the renewal is already recorded; a lost owner notice must not make ECPay retry
        print("ENQUEUE FAILED (owner notice lost)", msg.get("event_type"), msg.get("email"), msg.get("route"), repr(ex))


def _find(email, route, mtn):
    if email and route:
        it = TABLE.get_item(Key={"email": email, "route": route}).get("Item")
        if it and it.get("merchant_trade_no") == mtn:
            return it
    kw = {"FilterExpression": Attr("merchant_trade_no").eq(mtn)}  # fallback; fine at course scale
    while True:
        page = TABLE.scan(**kw)
        if page.get("Items"):
            return page["Items"][0]
        if "LastEvaluatedKey" not in page:
            return None
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def handler(event, context):
    p = form_params(event)
    cfg = ecpay_cfg()
    print("PeriodReturnURL callback", json.dumps({k: v for k, v in p.items() if k != "CheckMacValue"}, ensure_ascii=False))
    if not verify_cmv(p, cfg):
        print("CheckMacValueInvalid")
        return resp_text("0|CheckMacValueInvalid", 400)
    if p.get("MerchantID") != cfg["merchant_id"]:
        return resp_text("0|MerchantIDMismatch", 400)
    if p.get("SimulatePaid") == "1":
        print("SimulatePaid=1 - CMV ok, acknowledged, no bookkeeping")
        return resp_text("1|OK")
    mtn = p.get("MerchantTradeNo", "")
    item = _find(p.get("CustomField1", ""), p.get("CustomField2", ""), mtn)
    if not item:
        print("no subscription for MerchantTradeNo", mtn)
        return resp_text("1|OK")
    key = {"email": item["email"], "route": item["route"]}
    now = utcnow()

    if p.get("RtnCode") == "1":
        n = int(p.get("TotalSuccessTimes") or 0) or int(item.get("total_success_times", 1)) + 1
        base = max(now, parse_ts(item["current_period_end"])) if item.get("current_period_end") else now
        end = ts(period_end(base, item.get("period_type", "M"), int(item.get("period_frequency", 1))))
        status = "active" if item.get("subscription_status") in ("active", "pending_payment", "expired") \
            else item.get("subscription_status")
        try:
            TABLE.update_item(
                Key=key,
                UpdateExpression=("SET subscription_status=:s, current_period_end=:e, current_period_end_date=:ed, "
                                  "last_charged_at=:n, total_success_times=:t, failed_attempts=:z, updated_at=:n"),
                ConditionExpression="merchant_trade_no = :m AND (attribute_not_exists(total_success_times) OR total_success_times < :t)",
                ExpressionAttributeValues={":s": status, ":e": end, ":ed": tpe_date(end), ":n": ts(now),
                                           ":t": n, ":z": 0, ":m": mtn})
            print("RENEWED", key, "charge #%d" % n, "current_period_end", end, "status", status)
            notify({"event_type": "renewed", "email": item["email"], "route": item["route"], "merchant_trade_no": mtn,
                    "charge_no": n, "amount": p.get("Amount", ""), "current_period_end": end, "status": status,
                    "paid_at": p.get("ProcessDate", ""), "env": cfg.get("env", "")})
        except ClientError as ex:
            if ex.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            print("renewal #%d already recorded - no change" % n, key)
        return resp_text("1|OK")

    fails = int(item.get("failed_attempts", 0)) + 1
    expire = fails >= MAX_FAILS
    TABLE.update_item(
        Key=key,
        UpdateExpression="SET failed_attempts=:f, last_failed_at=:n, last_fail_msg=:msg, updated_at=:n"
                         + (", subscription_status=:x" if expire else ""),
        ExpressionAttributeValues=dict({":f": fails, ":n": ts(now), ":msg": p.get("RtnMsg", "")[:200]},
                                       **({":x": "expired"} if expire else {})))
    print("renewal FAILED", key, "consecutive failures", fails, "-> expired" if expire else "(ECPay will retry)")
    notify({"event_type": "renewal_failed", "email": item["email"], "route": item["route"], "merchant_trade_no": mtn,
            "fails": fails, "max_fails": MAX_FAILS, "expired": expire, "rtn_code": p.get("RtnCode", ""),
            "rtn_msg": p.get("RtnMsg", "")[:200], "current_period_end": item.get("current_period_end", ""),
            "paid_at": p.get("ProcessDate", ""), "env": cfg.get("env", "")})
    return resp_text("1|OK")
