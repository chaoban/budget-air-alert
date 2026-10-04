"""flight-parser: one route per invocation.

Fetch next month's cheapest fare from Travelpayouts (TWD = the gate, USD = best-effort
supplementary), scan `subscriptions` for that route, and enqueue every subscriber whose
target_price >= the TWD fare to `flight-fare-queue`.
M2 paywall (grace-aware gate): serve `active`, and `cancelled` while current_period_end >= now; a cancelled row
whose paid period has passed is lazily flipped to `expired`. pending_payment / expired / legacy rows are not served.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
TPE_TZ = timezone(timedelta(hours=8))
QUEUE_NAME = "flight-fare-queue"
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"  # same fixed-width UTC format every writer uses for current_period_end

_sm = boto3.client("secretsmanager")
_sqs = boto3.client("sqs")
_table = boto3.resource("dynamodb").Table("subscriptions")
_cache = {}


def _token():
    if "token" not in _cache:
        raw = _sm.get_secret_value(SecretId="flight/travelpayouts")["SecretString"]
        _cache["token"] = json.loads(raw)["token"]
    return _cache["token"]


def _queue_url():
    if "qurl" not in _cache:
        _cache["qurl"] = _sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
    return _cache["qurl"]


def next_month(now=None):
    now = now or datetime.now(TPE_TZ)
    y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return "%04d-%02d" % (y, m)


def fetch_cheapest(origin, destination, month, token, currency):
    q = urllib.parse.urlencode({"origin": origin, "destination": destination,
                                "depart_date": month, "currency": currency, "token": token})
    req = urllib.request.Request("https://api.travelpayouts.com/v1/prices/cheap?" + q,
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    if not body.get("success") or not body.get("data"):
        return None
    offers = body["data"].get(destination, {})
    if not offers:
        return None
    # Real keys are departure_at / return_at (not depart_date / return_date).
    # data[<DEST>] is keyed by number of transfers ("0" = direct, "1" = one stop, ...).
    stops, best = min(offers.items(), key=lambda kv: kv[1]["price"])
    out = {"price": best["price"], "currency": currency.upper(), "airline": best.get("airline"),
           "depart_date": best.get("departure_at"), "return_date": best.get("return_at")}
    if str(stops).isdigit():
        out["transfers"] = int(stops)
    return out


def _safe_fetch(origin, destination, month, token, currency):
    try:
        return fetch_cheapest(origin, destination, month, token, currency)
    except urllib.error.HTTPError as ex:
        print("travelpayouts %s HTTP %s for %s-%s" % (currency, ex.code, origin, destination))
    except (urllib.error.URLError, TimeoutError, ValueError) as ex:
        print("travelpayouts %s error for %s-%s: %s" % (currency, origin, destination, ex))
    return None


def _subscribers(route):
    kwargs = {"FilterExpression": Attr("route").eq(route)}
    while True:
        page = _table.scan(**kwargs)
        for it in page.get("Items", []):
            yield it
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def gate(it, now_s):
    """True if this subscriber is paid (or paid-through). Lazily retires grace-lapsed cancelled rows."""
    status = it.get("subscription_status")
    if status == "active":
        return True, "active"
    if status == "cancelled":
        end = str(it.get("current_period_end", ""))
        if end >= now_s:
            return True, "cancelled-in-grace until " + end
        try:
            _table.update_item(Key={"email": it["email"], "route": it["route"]},
                               UpdateExpression="SET subscription_status = :x, expired_at = :n, updated_at = :n",
                               ConditionExpression="subscription_status = :c AND current_period_end < :n",
                               ExpressionAttributeValues={":x": "expired", ":c": "cancelled", ":n": now_s})
            return False, "grace ended %s -> expired" % end
        except ClientError as ex:
            if ex.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return False, "grace ended (already updated)"
    return False, status or "no status (M1 row, unpaid)"


def handler(event, context):
    origin = event["origin"]
    destination = event["destination"]
    route = event.get("route") or "%s-%s" % (origin, destination)
    month = event.get("month") or next_month()
    token = _token()

    tw = _safe_fetch(origin, destination, month, token, "twd")
    if not tw:
        print("no TWD fare for", route, month, "(empty/429) - skipping")
        return {"ok": True, "route": route, "matched": 0}
    us = _safe_fetch(origin, destination, month, token, "usd")  # may be None - never block on it
    print("%s %s cheapest %s TWD (%s, %s -> %s)%s" % (
        route, month, tw["price"], tw["airline"], tw["depart_date"], tw["return_date"],
        " / %s USD" % us["price"] if us else " / USD n/a"))

    price = Decimal(str(tw["price"]))
    now_s = datetime.now(timezone.utc).strftime(TS_FMT)
    matched = skipped = gated = 0
    for it in _subscribers(route):
        served, why = gate(it, now_s)
        if not served:
            gated += 1
            print("gate skip", it["email"], route, "-", why)
            continue
        tp = it.get("target_price")
        if tp is None or Decimal(str(tp)) < price:
            skipped += 1
            continue
        body = {"email": it["email"], "route": route, "plan_name": it.get("plan_name"),
                "target_price": int(tp),
                "cheapest": {"price": tw["price"], "currency": "TWD", "airline": tw["airline"],
                             "depart_date": tw["depart_date"], "return_date": tw["return_date"]}}
        if "transfers" in tw:
            body["cheapest"]["transfers"] = tw["transfers"]
        if us:
            body["cheapest_usd"] = {"price": us["price"], "currency": "USD", "airline": us["airline"],
                                    "depart_date": us["depart_date"], "return_date": us["return_date"]}
        _sqs.send_message(QueueUrl=_queue_url(), MessageBody=json.dumps(body, ensure_ascii=False))
        matched += 1
        print("enqueued", it["email"], route, "target", int(tp), ">= fare", tw["price"], "-", why)
    print("%s matched=%d below_target=%d not_paid=%d" % (route, matched, skipped, gated))
    return {"ok": True, "route": route, "matched": matched, "fare_twd": tw["price"]}
