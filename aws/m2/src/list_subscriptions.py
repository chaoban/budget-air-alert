"""flight-list-subscriptions (GET /subscriptions) - the signed-in user's rows, incl. subscription_status."""
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table("subscriptions")


def handler(event, context):
    try:
        email = caller_email(event)
    except AuthError as ex:
        return resp_json(401, {"error": "請先登入 / sign in required", "detail": str(ex)})
    items, kw = [], {"KeyConditionExpression": Key("email").eq(email)}
    while True:
        page = TABLE.query(**kw)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    now_s = ts(utcnow())
    for it in items:
        # legacy M1 rows have no status: surface them as pending_payment so the user self-migrates by paying
        it.setdefault("subscription_status", "pending_payment")
        if it["subscription_status"] == "cancelled" and str(it.get("current_period_end", "")) < now_s:
            it["subscription_status"] = "expired"  # display only; the parser persists it
        it.pop("merchant_trade_no", None)
        it.pop("ecpay_trade_no", None)
        it.pop("ecpay_cancel_rtn", None)
    try:
        monthly = int(Decimal(str(ecpay_cfg()["amount"])))
    except Exception:
        monthly = None
    return resp_json(200, {"email": email, "monthly_price": monthly, "subscriptions": [to_json(i) for i in items]})
