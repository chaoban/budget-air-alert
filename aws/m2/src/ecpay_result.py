"""flight-ecpay-result (ANY /ecpay-result) - ECPay OrderResultURL arrives as a *browser POST*.
A static SPA would answer 405, so this only 302-redirects back to the app. No activation here (that's ReturnURL).
"""
SITE_URL = os.environ.get("SITE_URL", "https://budget-air-alert.vercel.app").strip().rstrip("/")


def handler(event, context):
    try:
        p = form_params(event)
    except Exception:
        p = {}
    ok = p.get("RtnCode", "1") == "1"
    route = p.get("CustomField2", "")
    q = urllib.parse.urlencode({"purchase": "success" if ok else "failed", **({"route": route} if route else {})})
    print("OrderResultURL", p.get("MerchantTradeNo"), "RtnCode", p.get("RtnCode"), "->", q)
    return {"statusCode": 302, "headers": {"Location": "%s/app?%s" % (SITE_URL, q), "Cache-Control": "no-store"},
            "body": ""}
