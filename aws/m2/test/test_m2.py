import importlib.util, json, os, sys, urllib.parse, io
import html as html_mod
from datetime import datetime, timezone, timedelta
from decimal import Decimal

os.environ.update(AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  API_BASE_URL="https://api.example.com", SITE_URL="https://site.example.com")
import boto3
from moto import mock_aws

BUILD = os.path.join(os.path.dirname(__file__), "..", "build")
VEC = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".claude", "skills", "ecpay", "test-vectors", "checkmacvalue.json")
CFG = {"merchant_id": "3002607", "hash_key": "pwFHCqoQZGmho4w6", "hash_iv": "EkRm7iFT261dpevs", "env": "stage", "amount": "300"}
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✓", msg)


def load(fn):
    spec = importlib.util.spec_from_file_location(fn.replace("-", "_"), os.path.join(BUILD, fn, "index.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def signed(params):
    m = load("flight-ecpay-return")
    p = dict(params); p["CheckMacValue"] = m.gen_cmv(p, CFG["hash_key"], CFG["hash_iv"]); return p


def form_event(p):
    return {"requestContext": {}, "body": urllib.parse.urlencode(p), "isBase64Encoded": False}


with mock_aws():
    ddb = boto3.client("dynamodb")
    ddb.create_table(TableName="subscriptions", BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}, {"AttributeName": "route", "AttributeType": "S"}],
                     KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}, {"AttributeName": "route", "KeyType": "RANGE"}])
    ddb.create_table(TableName="notification_history", BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sent_at", "AttributeType": "S"}],
                     KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sent_at", "KeyType": "RANGE"}])
    sqs = boto3.client("sqs")
    qs = sqs.create_queue(QueueName="flight-status-queue")["QueueUrl"]
    qf = sqs.create_queue(QueueName="flight-fare-queue")["QueueUrl"]
    sm = boto3.client("secretsmanager")
    sm.create_secret(Name="flight/ecpay", SecretString=json.dumps(CFG))
    sm.create_secret(Name="flight/resend", SecretString=json.dumps({"api_key": "re_x", "from": "onboarding@resend.dev"}))
    sm.create_secret(Name="flight/supabase", SecretString=json.dumps({"url": "https://sb.example.co", "publishable_key": "sb_publishable_x"}))
    sm.create_secret(Name="flight/travelpayouts", SecretString=json.dumps({"token": "t"}))
    T = boto3.resource("dynamodb").Table("subscriptions")

    def drain(q):
        out = []
        while True:
            r = sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10).get("Messages", [])
            if not r: return out
            for m in r:
                out.append(json.loads(m["Body"])); sqs.delete_message(QueueUrl=q, ReceiptHandle=m["ReceiptHandle"])

    print("[CMV vectors]")
    m = load("flight-ecpay-return")
    vec = json.load(open(VEC))["vectors"]
    for v in vec:
        if v.get("formula") == "ecticket" or str(v.get("method")).upper() != "SHA256":
            continue
        check(m.gen_cmv(v["params"], v["hashKey"], v["hashIV"]) == v["expected"], "vector: " + v["name"])

    print("[save_subscription]")
    save = load("flight-save-subscription")
    r = save.handler({"requestContext": {}, "headers": {}, "body": json.dumps({"plan_name": "tokyo", "target_price": 11000})}, None)
    check(r["statusCode"] == 401, "HTTP call without bearer token -> 401")
    r = save.handler({"email": "Me@Example.com", "plan_name": "tokyo", "target_price": 11000}, None)
    check(r["headers"]["content-type"].startswith("text/html"), "new subscription -> text/html form")
    body = r["body"]
    check("payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5" in body and "CheckMacValue" in body and 'name="PeriodType" value="M"' in body, "form posts to stage cashier with CMV + PeriodType=M")
    import re as _re
    fields = dict(_re.findall(r'name="([^"]+)" value="([^"]*)"', body))
    fields = {k: __import__("html").unescape(v) for k, v in fields.items()}
    check(fields["TotalAmount"] == fields["PeriodAmount"] == "300", "TotalAmount == PeriodAmount == 300")
    check(fields["CheckMacValue"] == save.gen_cmv(fields, CFG["hash_key"], CFG["hash_iv"]), "form CMV recomputes")
    check(fields["OrderResultURL"] == "https://api.example.com/ecpay-result" and fields["ReturnURL"].endswith("/ecpay-return"), "callback URLs point at the API (not the SPA)")
    check(len(fields["MerchantTradeNo"]) <= 20 and fields["MerchantTradeNo"].isalnum(), "MerchantTradeNo <= 20 alnum")
    row = T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]
    check(row["subscription_status"] == "pending_payment" and row["merchant_trade_no"] == fields["MerchantTradeNo"], "row pending_payment with merchant_trade_no")
    mtn = row["merchant_trade_no"]

    print("[ecpay_return]")
    ret = load("flight-ecpay-return")
    cb = {"MerchantID": "3002607", "MerchantTradeNo": mtn, "StoreID": "", "RtnCode": "1", "RtnMsg": "交易成功",
          "TradeNo": "2610041200001", "TradeAmt": "300", "PaymentDate": "2026/10/04 12:00:00", "PaymentType": "Credit_CreditCard",
          "PaymentTypeChargeFee": "8", "TradeDate": "2026/10/04 11:59:00", "SimulatePaid": "0",
          "CustomField1": "me@example.com", "CustomField2": "TPE-TYO", "CustomField3": "tokyo", "CustomField4": ""}
    bad = dict(cb); bad["CheckMacValue"] = ret.gen_cmv({k: v for k, v in cb.items() if v != ""}, CFG["hash_key"], CFG["hash_iv"])
    r = ret.handler(form_event(bad), None)
    check(r["statusCode"] == 400 and r["body"] == "0|CheckMacValueInvalid", "CMV computed WITHOUT empty fields is rejected (keep-empty rule)")
    sim = dict(cb); sim["SimulatePaid"] = "1"
    r = ret.handler(form_event(signed(sim)), None)
    check(r["body"] == "1|OK" and T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]["subscription_status"] == "pending_payment", "SimulatePaid=1 -> 1|OK but stays pending_payment")
    r = ret.handler(form_event(signed(cb)), None)
    row = T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]
    check(r["body"] == "1|OK" and r["headers"]["Content-Type"].startswith("text/plain"), "real callback -> text/plain 1|OK")
    check(row["subscription_status"] == "active" and len(row["current_period_end"]) == 20 and row["current_period_end"].endswith("Z"), "row active, current_period_end fixed-width Z format")
    exp_day = ret.add_period(datetime.now(timezone.utc).astimezone(ret.TPE_TZ), "M", 1).strftime("%Y/%m/%d")
    check(row["current_period_end"].endswith("T15:59:59Z") and row["current_period_end_date"] == exp_day,
          "paid through 23:59:59 Taipei on the due date (%s, %s)" % (row["current_period_end"], row["current_period_end_date"]))
    pe = lambda s, pt="M", n=1: ret.ts(ret.period_end(ret.parse_ts(s), pt, n))
    check(pe("2026-10-04T03:20:25Z") == "2026-11-04T15:59:59Z", "10/04 11:20 Taipei payment -> 11/04 23:59:59 Taipei")
    check(pe("2026-01-30T19:00:00Z") == "2026-02-28T15:59:59Z", "Taipei 1/31 03:00 -> 2/28 23:59:59 (Taipei calendar, not UTC 1/30)")
    check(pe("2026-11-04T15:59:59Z") == "2026-12-04T15:59:59Z", "renewal from a 23:59:59 end stays on 23:59:59")
    check(pe("2026-10-04T17:00:00Z", "D", 1) == "2026-10-06T15:59:59Z", "daily period uses the Taipei date (10/5 01:00 -> 10/6 23:59:59)")
    r = ret.handler(form_event(signed(cb)), None)
    msgs = drain(qs)
    check(r["body"] == "1|OK" and len(msgs) == 1 and msgs[0]["event_type"] == "welcome", "resend of same callback -> no second welcome")
    check(msgs[0]["env"] == "stage" and msgs[0]["ecpay_trade_no"] == "2610041200001" and msgs[0]["trade_amt"] == "300"
          and msgs[0]["paid_at"] == "2026/10/04 12:00:00", "welcome message carries env / TradeNo / TradeAmt / PaymentDate (owner notice)")

    print("[save in place / cancel / grace]")
    r = save.handler({"email": "me@example.com", "plan_name": "tokyo", "target_price": 9000}, None)
    check(r["headers"]["content-type"] == "application/json" and json.loads(r["body"])["subscription"]["subscription_status"] == "active", "active user target update -> JSON, still active")
    canc = load("flight-cancel-subscription")
    canc.ecpay_cancel = lambda cfg, mtn: ("10100058", "90100150 不存在的訂單編號")
    end_before = T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]["current_period_end"]
    r = canc.handler({"email": "me@example.com", "route": "TPE-TYO"}, None)
    row = T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]
    check(row["subscription_status"] == "cancelled" and row["current_period_end"] == end_before, "cancel -> cancelled (NOT expired), period end kept")
    r = canc.handler({"email": "me@example.com", "route": "TPE-TYO"}, None)
    msgs = drain(qs)
    check(json.loads(r["body"]).get("unchanged") and len(msgs) == 1 and msgs[0]["event_type"] == "cancel", "second cancel is a no-op, one cancel message")
    check(msgs[0]["env"] == "stage", "cancel message carries env (owner notice)")
    r = save.handler({"email": "me@example.com", "plan_name": "tokyo", "target_price": 8000}, None)
    check(r["headers"]["content-type"] == "application/json" and int(T.get_item(Key={"email": "me@example.com", "route": "TPE-TYO"})["Item"]["target_price"]) == 8000, "cancelled-in-grace can update target in place")
    r = canc.handler({"requestContext": {}, "headers": {}, "body": json.dumps({"route": "TPE-TYO"})}, None)
    check(r["statusCode"] == 401, "HTTP cancel without token -> 401")

    print("[cancel on env=prod: ECPay must confirm the stop]")
    cp = load("flight-cancel-subscription")
    cp._cache["flight/ecpay"] = dict(CFG, env="prod")
    pend = (datetime.now(timezone.utc) + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def active_row(email, mtn):
        T.put_item(Item={"email": email, "route": "TPE-SEL", "target_price": Decimal(9000), "subscription_status": "active",
                         "merchant_trade_no": mtn, "current_period_end": pend})

    def prod_cancel(email, rtn, exec_status):
        queried = []
        cp.ecpay_cancel = lambda cfg, mtn: rtn
        cp.ecpay_period_status = lambda cfg, mtn: queried.append(mtn) or exec_status
        r = cp.handler({"email": email, "route": "TPE-SEL"}, None)
        return r, T.get_item(Key={"email": email, "route": "TPE-SEL"})["Item"]["subscription_status"], drain(qs), queried

    active_row("p1@x.com", "FPPROD1")
    r, st_, msgs, q = prod_cancel("p1@x.com", ("10100050", "Cancel failed"), "1")
    check(r["statusCode"] == 502 and st_ == "active" and msgs == [] and q == ["FPPROD1"],
          "prod: Cancel not 1 + ExecStatus 1 (still running) -> 502, row stays active, no cancel mail")
    r, st_, msgs, q = prod_cancel("p1@x.com", (None, "network error timed out"), None)
    check(r["statusCode"] == 502 and st_ == "active" and msgs == [], "prod: network error + query unknown -> 502, stays active")
    r, st_, msgs, q = prod_cancel("p1@x.com", ("10100050", "already stopped"), "0")
    check(r["statusCode"] == 200 and st_ == "cancelled" and len(msgs) == 1, "prod: Cancel not 1 but ExecStatus 0 (已終止) -> cancelled")
    active_row("p2@x.com", "FPPROD2")
    r, st_, msgs, q = prod_cancel("p2@x.com", ("1", "停用成功"), "1")
    check(r["statusCode"] == 200 and st_ == "cancelled" and len(msgs) == 1 and q == [], "prod: Cancel RtnCode 1 -> cancelled without querying")
    T.put_item(Item={"email": "p3@x.com", "route": "TPE-SEL", "target_price": Decimal(9000),
                     "subscription_status": "pending_payment", "merchant_trade_no": "FPPROD3"})
    r, st_, msgs, q = prod_cancel("p3@x.com", ("10100058", "90100150 不存在的訂單編號"), None)
    check(r["statusCode"] == 200 and st_ == "expired" and msgs == [], "prod: unpaid row still expires locally on unknown order")
    for e in ("p1@x.com", "p2@x.com", "p3@x.com"):
        T.delete_item(Key={"email": e, "route": "TPE-SEL"})

    print("[parser gate]")
    now = datetime.now(timezone.utc); f = "%Y-%m-%dT%H:%M:%SZ"
    for email, st, end in [("a@x.com", "active", (now + timedelta(days=20)).strftime(f)),
                           ("g@x.com", "cancelled", (now + timedelta(days=5)).strftime(f)),
                           ("old@x.com", "cancelled", (now - timedelta(days=1)).strftime(f)),
                           ("p@x.com", "pending_payment", None), ("legacy@x.com", None, None)]:
        it = {"email": email, "route": "TPE-SEL", "target_price": Decimal(9000)}
        if st: it["subscription_status"] = st
        if end: it["current_period_end"] = end
        T.put_item(Item=it)
    par = load("flight-parser")
    par.fetch_cheapest = lambda o, d, mth, tok, cur: {"price": 6386 if cur == "twd" else 201, "currency": cur.upper(), "airline": "ZE", "depart_date": "x", "return_date": "y", "transfers": 0}
    out = par.handler({"origin": "TPE", "destination": "SEL", "route": "TPE-SEL"}, None)
    got = sorted(m["email"] for m in drain(qf))
    check(got == ["a@x.com", "g@x.com"], "only active + cancelled-in-grace enqueued (got %s)" % got)
    check(T.get_item(Key={"email": "old@x.com", "route": "TPE-SEL"})["Item"]["subscription_status"] == "expired", "grace-lapsed cancelled row flipped to expired")
    check("subscription_status" not in T.get_item(Key={"email": "legacy@x.com", "route": "TPE-SEL"})["Item"], "legacy row untouched (just not served)")
    # simulate hook: one subscriber, simulated fare, simulated clock never persists an expiry
    T.put_item(Item={"email": "g2@x.com", "route": "TPE-SEL", "target_price": Decimal(9000), "subscription_status": "cancelled",
                     "current_period_end": (now + timedelta(days=5)).strftime(f)})
    sim = {"origin": "TPE", "destination": "SEL", "route": "TPE-SEL", "simulate": {"email": "g2@x.com", "price_twd": 5000}}
    par.handler(sim, None)
    msgs = drain(qf)
    check([m["email"] for m in msgs] == ["g2@x.com"] and msgs[0]["cheapest"]["price"] == 5000 and "cheapest_usd" not in msgs[0],
          "simulate: only the named subscriber, simulated TWD fare, no USD")
    later = (now + timedelta(days=5, seconds=1)).strftime(f)
    par.handler(dict(sim, simulate={"email": "g2@x.com", "price_twd": 5000, "now": later}), None)
    check(drain(qf) == [] and T.get_item(Key={"email": "g2@x.com", "route": "TPE-SEL"})["Item"]["subscription_status"] == "cancelled",
          "simulate now past period end: not enqueued and row NOT flipped")
    on_last = (now + timedelta(days=5) - timedelta(minutes=1)).strftime(f)
    par.handler(dict(sim, simulate={"email": "g2@x.com", "price_twd": 5000, "now": on_last}), None)
    check([m["email"] for m in drain(qf)] == ["g2@x.com"], "simulate now just before period end: still enqueued")
    check(par.handler(dict(sim, simulate={"price_twd": 5000}), None)["ok"] is False, "simulate without email rejected")
    T.put_item(Item={"email": "g3@x.com", "route": "TPE-SEL", "target_price": Decimal(9000), "subscription_status": "cancelled",
                     "current_period_end": "2026-11-04T15:59:59Z"})
    s3 = dict(sim, simulate={"email": "g3@x.com", "price_twd": 5000, "now": "2026-11-04T15:59:59Z"})
    par.handler(s3, None)
    check(len(drain(qf)) == 1, "11/04 23:59:59 Taipei: still served")
    par.handler(dict(s3, simulate=dict(s3["simulate"], now="2026-11-04T16:00:00Z")), None)
    check(drain(qf) == [], "11/05 00:00:00 Taipei: no longer served")

    print("[ecpay_period]")
    per = load("flight-ecpay-period")
    drain(qs)
    T.put_item(Item={"email": "r@x.com", "route": "TPE-LON", "subscription_status": "active", "merchant_trade_no": "FPTEST1",
                     "current_period_end": (now + timedelta(hours=1)).strftime(f), "total_success_times": 1, "period_type": "M", "period_frequency": 1})
    pc = {"MerchantID": "3002607", "MerchantTradeNo": "FPTEST1", "StoreID": "", "RtnCode": "1", "RtnMsg": "交易成功", "PeriodType": "M",
          "Frequency": "1", "ExecTimes": "999", "Amount": "300", "Gwsr": "123", "ProcessDate": "2026/11/04 10:00:00", "AuthCode": "777777",
          "FirstAuthAmount": "300", "TotalSuccessTimes": "2", "CustomField1": "r@x.com", "CustomField2": "TPE-LON", "CustomField3": "london", "CustomField4": ""}
    per.handler(form_event(signed(pc)), None)
    e1 = T.get_item(Key={"email": "r@x.com", "route": "TPE-LON"})["Item"]["current_period_end"]
    check(e1 > (now + timedelta(days=27)).strftime(f) and e1.endswith("T15:59:59Z"), "renewal extends current_period_end by a month, to 23:59:59 Taipei (%s)" % e1)
    per.handler(form_event(signed(pc)), None)
    check(T.get_item(Key={"email": "r@x.com", "route": "TPE-LON"})["Item"]["current_period_end"] == e1, "renewal resend does not extend twice")
    msgs = drain(qs)
    check(len(msgs) == 1 and msgs[0]["event_type"] == "renewed" and msgs[0]["charge_no"] == 2 and msgs[0]["current_period_end"] == e1
          and msgs[0]["amount"] == "300" and msgs[0]["env"] == "stage" and msgs[0]["status"] == "active",
          "renewal -> one 'renewed' owner notice (the resend adds none)")
    fail = dict(pc); fail["RtnCode"] = "10100248"; fail["RtnMsg"] = "拒絕交易"
    for i in range(5):
        per.handler(form_event(signed(fail)), None)
    check(T.get_item(Key={"email": "r@x.com", "route": "TPE-LON"})["Item"]["subscription_status"] == "active", "5 failed renewals -> still active")
    per.handler(form_event(signed(fail)), None)
    check(T.get_item(Key={"email": "r@x.com", "route": "TPE-LON"})["Item"]["subscription_status"] == "expired", "6th consecutive failure -> expired")
    msgs = drain(qs)
    check([m["fails"] for m in msgs] == [1, 2, 3, 4, 5, 6] and [m["expired"] for m in msgs] == [False] * 5 + [True]
          and all(m["event_type"] == "renewal_failed" and m["rtn_msg"] == "拒絕交易" and m["max_fails"] == 6 for m in msgs),
          "each failed renewal -> 'renewal_failed' owner notice, the 6th flagged expired")
    T.put_item(Item={"email": "r2@x.com", "route": "TPE-LON", "subscription_status": "active", "merchant_trade_no": "FPTEST2",
                     "current_period_end": (now + timedelta(hours=1)).strftime(f), "total_success_times": 1, "period_type": "M", "period_frequency": 1})
    real_send = per._sqs.send_message
    per._sqs.send_message = lambda **kw: (_ for _ in ()).throw(RuntimeError("sqs down"))
    r = per.handler(form_event(signed(dict(pc, MerchantTradeNo="FPTEST2", CustomField1="r2@x.com"))), None)
    per._sqs.send_message = real_send
    check(r["body"] == "1|OK" and T.get_item(Key={"email": "r2@x.com", "route": "TPE-LON"})["Item"]["total_success_times"] == 2,
          "queue down: renewal still recorded and ECPay still gets 1|OK")

    print("[ecpay_result / list]")
    res = load("flight-ecpay-result")
    r = res.handler(form_event({"RtnCode": "1", "CustomField2": "TPE-TYO", "MerchantTradeNo": mtn}), None)
    check(r["statusCode"] == 302 and r["headers"]["Location"].startswith("https://site.example.com/app?purchase=success"), "OrderResultURL POST -> 302 /app?purchase=success")
    lst = load("flight-list-subscriptions")
    r = json.loads(lst.handler({"email": "legacy@x.com"}, None)["body"])
    check(r["subscriptions"][0]["subscription_status"] == "pending_payment", "legacy row surfaced as pending_payment")
    r = json.loads(lst.handler({"email": "me@example.com"}, None)["body"])
    check("merchant_trade_no" not in r["subscriptions"][0], "trade-no not exposed to the browser")

    print("[status_notification]")
    st = load("flight-status-notification")
    sent = []
    st.send = lambda to, s, h, t: (sent.append((to, s)) or (200, {"id": "x%d" % len(sent)}))
    welcome = {"event_type": "welcome", "email": "me@example.com", "route": "TPE-TYO", "merchant_trade_no": mtn, "target_price": 11000, "amount": 300, "current_period_end": end_before}
    rec = lambda m, i: {"messageId": str(i), "body": json.dumps(m)}
    st.handler({"Records": [rec(welcome, 1), rec(welcome, 2)]}, None)
    check(len(sent) == 1 and sent[0][1].startswith("✅ 訂閱成功：台北 → 東京"), "welcome sent once even if delivered twice")
    st.send = lambda *a: (429, "rate")
    cm = {"event_type": "cancel", "email": "me@example.com", "route": "TPE-TYO", "merchant_trade_no": mtn, "target_price": 8000, "current_period_end": end_before}
    out = st.handler({"Records": [rec(cm, 3)]}, None)
    check(out["batchItemFailures"] == [{"itemIdentifier": "3"}], "429 -> batch item failure (SQS retries)")
    st.send = lambda to, s, h, t: (sent.append((to, s)) or (200, {"id": "y"}))
    st.handler({"Records": [rec(cm, 4)]}, None)
    check(sent[-1][1] == "已取消訂閱：台北 → 東京", "cancel email sent on retry after transient failure")
    # permanent 4xx (e.g. Resend sandbox 403 for a non-owner address) -> dropped once, never re-sent
    st.send = lambda to, s, h, t: (sent.append((to, s)) or (403, "only your own email"))
    other = dict(welcome, email="other@example.com")
    n0 = len(sent)
    out = st.handler({"Records": [rec(other, 5)]}, None)
    row = boto3.resource("dynamodb", region_name="us-east-1").Table("notification_history").get_item(
        Key={"pk": "status#welcome#other@example.com#TPE-TYO#" + mtn, "sent_at": "#once"})["Item"]
    check(out["batchItemFailures"] == [] and row["state"] == "dropped" and "own email" in row["error"],
          "permanent 4xx -> marked dropped (reserved word 'error' handled)")
    st.handler({"Records": [rec(other, 6)]}, None)
    check(len(sent) == n0 + 1, "dropped message is not re-sent")
    s, h, t = st.render(cm)
    open(os.path.join(BUILD, "cancel.html"), "w").write("<meta charset=utf-8>" + h)
    s, h, t = st.render(welcome)
    open(os.path.join(BUILD, "welcome.html"), "w").write("<meta charset=utf-8>" + h)

    print("[owner (admin) notices]")
    rn = {"event_type": "renewed", "email": "r@x.com", "route": "TPE-LON", "merchant_trade_no": "FPTEST1", "charge_no": 2,
          "amount": "300", "current_period_end": "2026-12-04T15:59:59Z", "status": "active", "paid_at": "2026/11/04 10:00:00", "env": "prod"}
    sent.clear()
    st.send = lambda to, s, h, t: (sent.append((to, s)) or (200, {"id": "a%d" % len(sent)}))
    out = st.handler({"Records": [rec(rn, 9)]}, None)
    check(out["batchItemFailures"] == [] and sent == [], "no admin_to in flight/resend -> owner notice skipped quietly")
    sm.put_secret_value(SecretId="flight/resend", SecretString=json.dumps(
        {"api_key": "re_x", "from": "onboarding@resend.dev", "admin_to": "boss@example.com"}))
    st._cache.pop("flight/resend", None)
    w2 = dict(welcome, email="new@example.com", merchant_trade_no="FPADMIN1", env="stage", ecpay_trade_no="2610070000001",
              trade_amt="300", paid_at="2026/10/07 10:00:00")
    st.handler({"Records": [rec(w2, 10), rec(w2, 11)]}, None)
    check([to for to, _ in sent] == ["new@example.com", ["boss@example.com"]], "welcome -> subscriber mail + one owner copy (redelivery adds none)")
    check(sent[1][1] == "[測試] 🔔 新訂閱：台北 → 東京｜new@example.com｜NT$300", "owner subject: [測試] + route + member + amount")
    sent.clear()
    st.handler({"Records": [rec(rn, 12), rec(rn, 13)]}, None)
    check(len(sent) == 1 and sent[0][0] == ["boss@example.com"] and sent[0][1] == "💰 續扣成功（第 2 期）：台北 → 倫敦｜r@x.com",
          "renewed -> owner only, once; prod has no [測試] tag")
    sent.clear()
    st.handler({"Records": [rec(dict(rn, charge_no=3), 14)]}, None)
    check(len(sent) == 1 and "第 3 期" in sent[0][1], "the next charge is a new notice")
    s, h, t = st.render_admin(dict(rn, status="cancelled"))
    check(s.startswith("⚠️ 已取消的訂閱被續扣（第 2 期）") and "仍然扣款" in h and t.startswith("⚠️"),
          "renewal on a cancelled row -> flagged subject + refund warning in the notice")
    rf = {"event_type": "renewal_failed", "email": "r@x.com", "route": "TPE-LON", "merchant_trade_no": "FPTEST1", "fails": 2,
          "max_fails": 6, "expired": False, "rtn_code": "10100248", "rtn_msg": "拒絕交易", "current_period_end": "2026-12-04T15:59:59Z",
          "paid_at": "2026/12/04 10:00:00", "env": "stage"}
    sent.clear()
    st.handler({"Records": [rec(rf, 15), rec(dict(rf, fails=6, expired=True), 16)]}, None)
    check([s for _, s in sent] == ["[測試] ⚠️ 續扣失敗（連續第 2 次）：台北 → 倫敦｜r@x.com",
                                   "[測試] ⛔ 續扣連續失敗 6 次，訂閱已終止：台北 → 倫敦｜r@x.com"], "renewal_failed -> owner notice; the 6th says terminated")
    sent.clear()
    st.handler({"Records": [rec(cm, 17)]}, None)
    check(len(sent) == 1 and sent[0][0] == ["boss@example.com"] and sent[0][1].startswith("[測試] 👋 取消訂閱：台北 → 東京"),
          "cancel redelivered after admin_to was added -> owner copy only, subscriber mail not repeated")

    def flaky(to, s, h, t):
        if isinstance(to, list):
            return 500, "boom"
        sent.append((to, s)); return 200, {"id": "z"}
    w3 = dict(w2, email="new2@example.com", merchant_trade_no="FPADMIN2")
    sent.clear(); st.send = flaky
    out = st.handler({"Records": [rec(w3, 18)]}, None)
    check(out["batchItemFailures"] == [{"itemIdentifier": "18"}] and [to for to, _ in sent] == ["new2@example.com"],
          "owner mail 5xx -> SQS retry; the subscriber mail already went out")
    st.send = lambda to, s, h, t: (sent.append((to, s)) or (200, {"id": "w"}))
    out = st.handler({"Records": [rec(w3, 19)]}, None)
    check(out["batchItemFailures"] == [] and [to for to, _ in sent] == ["new2@example.com", ["boss@example.com"]],
          "retry -> owner mail sent, subscriber mail NOT sent twice")

    def flaky2(to, s, h, t):
        if not isinstance(to, list):
            return 429, "rate"
        sent.append((to, s)); return 200, {"id": "q"}
    sent.clear(); st.send = flaky2
    out = st.handler({"Records": [rec(dict(w2, email="new3@example.com", merchant_trade_no="FPADMIN3"), 20)]}, None)
    check(out["batchItemFailures"] == [{"itemIdentifier": "20"}] and [to for to, _ in sent] == [["boss@example.com"]],
          "subscriber 429 does not hold back the owner copy")
    sent.clear(); st.send = lambda to, s, h, t: (sent.append((to, s)) or (200, {"id": "u"}))
    out = st.handler({"Records": [rec({"event_type": "weird", "email": "a@x.com", "route": "TPE-TYO"}, 21)]}, None)
    check(out["batchItemFailures"] == [] and sent == [], "unknown event_type still dropped")
    sm.put_secret_value(SecretId="flight/resend", SecretString=json.dumps(
        {"api_key": "re_x", "from": "onboarding@resend.dev", "admin_to": "boss@example.com, ops@example.com, not-an-email"}))
    st._cache.pop("flight/resend", None)
    check(st.admin_recipients() == ["boss@example.com", "ops@example.com"], "admin_to: comma-separated, invalid entries ignored")
    for name, m in (("admin-welcome", w2), ("admin-renewed", rn), ("admin-renewal-failed", dict(rf, fails=6, expired=True)),
                    ("admin-cancel", cm), ("admin-renewed-after-cancel", dict(rn, status="cancelled"))):
        s, h, t = st.render_admin(m)
        open(os.path.join(BUILD, name + ".html"), "w").write("<meta charset=utf-8><title>%s</title>" % html_mod.escape(s) + h)
        open(os.path.join(BUILD, name + ".txt"), "w").write(s + "\n\n" + t)

print("\nALL OK:", ok, "checks")
