"""Fold src/common.py into each handler -> <OUT>/<function>/index.py (single-file index.handler).
Usage: python3 build.py            # -> aws/m2/build/ (what the tests load)
       python3 build.py ../lambdas # -> refresh aws/lambdas/<function>/index.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "build")
FUNCS = {"flight-save-subscription": "save_subscription", "flight-list-subscriptions": "list_subscriptions",
         "flight-ecpay-return": "ecpay_return", "flight-ecpay-period": "ecpay_period",
         "flight-ecpay-result": "ecpay_result", "flight-cancel-subscription": "cancel_subscription",
         "flight-status-notification": "status_notification"}
common = open(os.path.join(SRC, "common.py")).read()
for fn, mod in FUNCS.items():
    h = open(os.path.join(SRC, mod + ".py")).read()
    doc, rest = "", h
    if h.startswith('"""'):
        end = h.index('"""', 3) + 3
        doc, rest = h[:end] + "\n", h[end:]
    os.makedirs(os.path.join(OUT, fn), exist_ok=True)
    open(os.path.join(OUT, fn, "index.py"), "w").write(doc + "# Built from m2/src/common.py + m2/src/%s.py (single-file index.handler)\n" % mod + common + rest)
os.makedirs(os.path.join(OUT, "flight-parser"), exist_ok=True)
open(os.path.join(OUT, "flight-parser", "index.py"), "w").write(open(os.path.join(SRC, "parser.py")).read())
for fn in list(FUNCS) + ["flight-parser"]:
    p = os.path.join(OUT, fn, "index.py"); compile(open(p).read(), p, "exec"); print(fn, os.path.getsize(p))
