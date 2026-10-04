"""flight-ecpay-return (POST /ecpay-return) - ECPay ReturnURL, first period of 信用卡定期定額.
The source of truth for activation. Verify CMV -> (not SimulatePaid, RtnCode == "1") -> pending_payment -> active,
set current_period_end, enqueue {event_type: "welcome"}. Always answer the literal text 1|OK once handled.
"""
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
