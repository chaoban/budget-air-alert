"""flight-ecpay-period (POST /ecpay-period) - ECPay PeriodReturnURL, 2nd charge onward.
Success -> extend current_period_end by one period (idempotent on TotalSuccessTimes).
Failure -> count it; ECPay retries and only terminates after 6 consecutive failures -> then expired.
"""
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

TABLE = boto3.resource("dynamodb").Table("subscriptions")
MAX_FAILS = 6


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
        end = ts(add_period(base, item.get("period_type", "M"), int(item.get("period_frequency", 1))))
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
    return resp_text("1|OK")
