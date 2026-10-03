import base64, json, re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import boto3

PLANS = {"tokyo": {"origin": "TPE", "destination": "TYO"},
         "seoul": {"origin": "TPE", "destination": "SEL"},
         "london": {"origin": "TPE", "destination": "LON"}}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TABLE = boto3.resource("dynamodb").Table("subscriptions")


def resp(code, obj):
    return {"statusCode": code, "headers": {"content-type": "application/json"},
            "body": json.dumps(obj, ensure_ascii=False)}


def to_json(item):
    return {k: (int(v) if isinstance(v, Decimal) else v) for k, v in item.items()}


def handler(event, context):
    raw = event.get("body") if isinstance(event, dict) else None
    try:
        if raw is None:
            data = event
        else:
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return resp(400, {"error": "invalid JSON body"})

    email = str(data.get("email", "")).strip().lower()
    plan_name = str(data.get("plan_name", "")).strip().lower()
    if not EMAIL_RE.match(email):
        return resp(400, {"error": "invalid email"})
    if plan_name not in PLANS:
        return resp(400, {"error": "plan_name must be one of " + ", ".join(PLANS)})
    try:
        tp = Decimal(str(data.get("target_price"))).to_integral_value()
    except (InvalidOperation, ValueError, TypeError):
        return resp(400, {"error": "target_price must be a number (TWD)"})
    if not tp.is_finite() or tp <= 0 or tp > 1000000:
        return resp(400, {"error": "target_price must be between 1 and 1,000,000 TWD"})

    plan = PLANS[plan_name]
    route = plan["origin"] + "-" + plan["destination"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # M1: no subscription_status / payment fields (those arrive in M2)
    out = TABLE.update_item(
        Key={"email": email, "route": route},
        UpdateExpression=("SET plan_name=:p, origin=:o, destination=:d, target_price=:t, "
                          "currency=:c, updated_at=:n, created_at=if_not_exists(created_at,:n)"),
        ExpressionAttributeValues={":p": plan_name, ":o": plan["origin"], ":d": plan["destination"],
                                   ":t": tp, ":c": "TWD", ":n": now},
        ReturnValues="ALL_NEW")
    item = to_json(out["Attributes"])
    print("saved", json.dumps(item, ensure_ascii=False))
    return resp(200, {"ok": True, "subscription": item})
