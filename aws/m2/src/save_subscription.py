"""flight-save-subscription (POST /subscribe) - M2.

- active, or cancelled but still inside the paid period -> update target_price in place, JSON response.
- anything else (new / pending_payment / expired / legacy M1 row) -> subscription_status = pending_payment,
  new MerchantTradeNo, and an ECPay 信用卡定期定額 auto-submit form (text/html) the browser posts to the cashier.
Callbacks (flight-ecpay-return / -period) are the only writers of `active`.
"""
import html
import secrets
import string

TABLE = boto3.resource("dynamodb").Table("subscriptions")
API_BASE = os.environ.get("API_BASE_URL", "").strip().rstrip("/")
SITE_URL = os.environ.get("SITE_URL", "https://budget-air-alert.vercel.app").strip().rstrip("/")
PERIOD_TYPE = os.environ.get("PERIOD_TYPE", "M").strip()          # D only for the renewal test
FREQUENCY = int(os.environ.get("FREQUENCY", "1"))
EXEC_TIMES = int(os.environ.get("EXEC_TIMES", "999"))
ALNUM = string.ascii_uppercase + string.digits


def _trade_no():
    # <= 20 chars, alphanumeric, unique: FP + yymmddHHMMSS + 6 random
    return "FP" + datetime.now(TPE_TZ).strftime("%y%m%d%H%M%S") + "".join(secrets.choice(ALNUM) for _ in range(6))


def _in_grace(item, now_s):
    return item.get("subscription_status") == "cancelled" and str(item.get("current_period_end", "")) >= now_s


def checkout_form(cfg, mtn, email, route, plan_name):
    amount = str(int(Decimal(str(cfg["amount"]))))
    params = {
        "MerchantID": cfg["merchant_id"], "MerchantTradeNo": mtn,
        "MerchantTradeDate": datetime.now(TPE_TZ).strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio", "ChoosePayment": "Credit", "EncryptType": "1",
        "TotalAmount": amount, "PeriodAmount": amount,
        "PeriodType": PERIOD_TYPE, "Frequency": str(FREQUENCY), "ExecTimes": str(EXEC_TIMES),
        "TradeDesc": "Flight Price Notifier monthly plan",
        "ItemName": "Flight Price Notifier %s monthly plan" % route,
        "ReturnURL": API_BASE + "/ecpay-return",
        "PeriodReturnURL": API_BASE + "/ecpay-period",
        "OrderResultURL": API_BASE + "/ecpay-result",
        "ClientBackURL": SITE_URL + "/app",
        "CustomField1": email, "CustomField2": route, "CustomField3": plan_name,
    }
    params["CheckMacValue"] = gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])
    action = "https://%s/Cashier/AioCheckOut/V5" % ecpay_host(cfg)
    inputs = "\n".join('<input type="hidden" name="%s" value="%s">' % (html.escape(k), html.escape(str(v)))
                       for k, v in params.items())
    return ('<!doctype html><html><head><meta charset="utf-8"><title>前往綠界付款…</title></head>'
            '<body><p style="font-family:sans-serif">正在前往綠界付款頁面…</p>'
            '<form id="ecpay" action="%s" method="post">\n%s\n</form>'
            '<script>document.forms[0].submit()</script></body></html>') % (html.escape(action), inputs)


def handler(event, context):
    try:
        email = caller_email(event)
    except AuthError as ex:
        return resp_json(401, {"error": "請先登入 / sign in required", "detail": str(ex)})
    try:
        data = http_body(event)
    except (ValueError, TypeError):
        return resp_json(400, {"error": "invalid JSON body"})

    plan_name = str(data.get("plan_name", "")).strip().lower()
    if plan_name not in PLANS:
        return resp_json(400, {"error": "plan_name must be one of " + ", ".join(PLANS)})
    try:
        tp = Decimal(str(data.get("target_price"))).to_integral_value()
        if not tp.is_finite() or tp <= 0 or tp > 1000000:
            raise ValueError
    except Exception:
        return resp_json(400, {"error": "target_price must be between 1 and 1,000,000 TWD"})

    plan = PLANS[plan_name]
    route = plan["origin"] + "-" + plan["destination"]
    now_s = ts(utcnow())
    key = {"email": email, "route": route}
    item = TABLE.get_item(Key=key).get("Item") or {}
    status = item.get("subscription_status")

    if status == "active" or _in_grace(item, now_s):
        # paid (or paid-through) subscriber: change the target in place - no re-payment, status untouched
        out = TABLE.update_item(Key=key, UpdateExpression="SET target_price=:t, updated_at=:n",
                                ConditionExpression="subscription_status = :s",
                                ExpressionAttributeValues={":t": tp, ":n": now_s, ":s": status},
                                ReturnValues="ALL_NEW")["Attributes"]
        print("target updated in place", email, route, int(tp), "status", status)
        return resp_json(200, {"ok": True, "updated": True, "subscription": to_json(out)})

    cfg = ecpay_cfg()
    mtn = _trade_no()
    TABLE.update_item(
        Key=key,
        UpdateExpression=("SET plan_name=:p, origin=:o, destination=:d, target_price=:t, currency=:c, "
                          "subscription_status=:s, merchant_trade_no=:m, period_type=:pt, period_frequency=:pf, "
                          "amount=:a, updated_at=:n, created_at=if_not_exists(created_at,:n)"),
        ExpressionAttributeValues={":p": plan_name, ":o": plan["origin"], ":d": plan["destination"], ":t": tp,
                                   ":c": "TWD", ":s": "pending_payment", ":m": mtn, ":pt": PERIOD_TYPE,
                                   ":pf": FREQUENCY, ":a": Decimal(str(cfg["amount"])), ":n": now_s})
    print("pending_payment", email, route, "target", int(tp), "MerchantTradeNo", mtn, "previous status", status)
    return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8"},
            "body": checkout_form(cfg, mtn, email, route, plan_name)}
