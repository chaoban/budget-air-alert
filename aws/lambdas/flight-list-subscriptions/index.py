import json, re
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TABLE = boto3.resource("dynamodb").Table("subscriptions")


def resp(code, obj):
    return {"statusCode": code, "headers": {"content-type": "application/json"},
            "body": json.dumps(obj, ensure_ascii=False)}


def to_json(item):
    return {k: (int(v) if isinstance(v, Decimal) else v) for k, v in item.items()}


def handler(event, context):
    # NOTE: trusts the client-supplied email (no auth) - fine for the course;
    # production would verify the Supabase JWT here first.
    qs = (event.get("queryStringParameters") or {}) if isinstance(event, dict) else {}
    email = str(qs.get("email") or event.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return resp(400, {"error": "query parameter email is required"})
    items, kwargs = [], {"KeyConditionExpression": Key("email").eq(email)}
    while True:
        page = TABLE.query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return resp(200, {"email": email, "subscriptions": [to_json(i) for i in items]})
