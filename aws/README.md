# AWS backend (M2 — paid price-drop notifier, ECPay 信用卡定期定額)

Source of the Lambdas deployed in **us-east-1**. Each function is a single `index.py`
(`index.handler`, python3.12, boto3 + stdlib only, no layer, no VPC).

| Function | Deploy | Trigger |
|---|---|---|
| `flight-save-subscription` | CloudFormation stack, code `s3://flight-config-<ACCOUNT_ID>/lambda/m2/…` | API GW `POST /subscribe` |
| `flight-list-subscriptions` | CloudFormation stack, code `s3://…/lambda/m2/…` | API GW `GET /subscriptions` |
| `flight-ecpay-return` | `s3://…/lambda/m2/…` | API GW `POST /ecpay-return` (ECPay ReturnURL — first charge) |
| `flight-ecpay-period` | `s3://…/lambda/m2/…` | API GW `POST /ecpay-period` (ECPay PeriodReturnURL — renewals) |
| `flight-ecpay-result` | `s3://…/lambda/m2/…` | API GW `ANY /ecpay-result` (ECPay OrderResultURL browser POST → 302 to `/app?purchase=…`) |
| `flight-cancel-subscription` | `s3://…/lambda/m2/…` | API GW `POST /cancel` |
| `flight-status-notification` | `s3://…/lambda/m2/…` | SQS `flight-status-queue` (batch 5, ReportBatchItemFailures) |
| `flight-parser-wrapper` | `s3://…/lambda/wrapper.zip` | EventBridge `flight-price-check` (`rate(30 minutes)`) |
| `flight-parser` | `s3://…/lambda/m2/…` | async invoke from the wrapper, one per route |
| `flight-fare-notification` | `s3://…/lambda/fare-notification.zip` | SQS `flight-fare-queue` (batch 5, ReportBatchItemFailures) |
| `flight-git-push` | CloudFormation stack (inline) | manual — deploy helper that commits to this repo via the GitHub API |

## Auth

`/subscribe`, `/subscriptions` and `/cancel` require `Authorization: Bearer <Supabase access token>`.
The Lambda verifies it with `GET {supabase_url}/auth/v1/user` and uses **that** email — any `email`
in the query/body is ignored. Missing/invalid token → `401`. (A direct `aws lambda invoke` without an
API Gateway `requestContext` may pass `email` in the payload — IAM-only, used for tests.)

## Subscription lifecycle (`subscriptions.subscription_status`)

```
pending_payment ──ReturnURL RtnCode=1──▶ active ──/cancel──▶ cancelled ──current_period_end passes──▶ expired
       ▲                                  │  ▲ PeriodReturnURL extends current_period_end
       └──────── /subscribe (re-pay) ◀────┘  └ 6 consecutive renewal failures ─▶ expired
```

- Only the **CheckMacValue-verified** callbacks write `active` (`flight-ecpay-return` / `flight-ecpay-period`);
  `SimulatePaid=1` is acknowledged but never activates. Callbacks always reply `1|OK` (text/plain).
- `/subscribe` returns `text/html` (ECPay auto-submit checkout form) for new / unpaid / expired rows, or JSON
  (in-place target update, no re-payment) for `active` and `cancelled`-in-grace rows.
- `/cancel` calls ECPay `CreditCardPeriodAction Action=Cancel` (stops renewals), sets `cancelled` and keeps
  `current_period_end` (grace). Unpaid rows go straight to `expired`.
- **Paywall:** `flight-parser` serves only `active` and `cancelled` rows with `current_period_end >= now`,
  and lazily flips grace-lapsed `cancelled` rows to `expired`. Legacy M1 rows (no status) are not served and
  show as 未完成付款 in the UI until the user pays.
- Welcome / cancel emails: `flight-status-queue` → `flight-status-notification` → Resend, exactly once per
  `(event, email, route, MerchantTradeNo)` via a conditional claim row in `notification_history`
  (`pk = status#…`, `sent_at = #once`).

Times are UTC strings `YYYY-MM-DDTHH:MM:SSZ` (compared as strings). A paid period runs **through 23:59:59 Taipei
on its due date** (`current_period_end` = `…T15:59:59Z`; calendar math on the Taipei date, e.g. 1/31 → 2/28);
`current_period_end_date` is that Taipei date.

## Data, secrets, IAM

- DynamoDB `subscriptions` (email / route) and `notification_history` (pk / sent_at).
- Secrets Manager: `flight/ecpay` `{merchant_id, hash_key, hash_iv, env, amount}` (stage test merchant,
  `amount` = monthly TWD price, read at checkout and shown in the UI), `flight/supabase`, `flight/travelpayouts`,
  `flight/resend`.
- IAM: all runtime Lambdas use `flight-lambda-role` with the inline policy in `iam/flight-data-policy.json`.

## Source, build, test (`m2/`)

The M2 functions share `m2/src/common.py` (CheckMacValue, ECPay host, time helpers, Supabase auth).
`build.py` folds it into each handler so every deployed function stays a single file:

```bash
cd aws/m2
python3 build.py && python3 test/test_m2.py   # moto tests (49 checks), loads aws/m2/build/
python3 build.py ../lambdas                    # refresh aws/lambdas/<function>/index.py
```

Redeploy a function: zip its `index.py` (`zip -j x.zip index.py`), upload to a **new** S3 key under
`lambda/m2/`, check the S3 ETag equals the local md5, then
`aws lambda update-function-code --s3-bucket … --s3-key … --region us-east-1` (or update the CloudFormation
stack's `S3Key` for save/list).

Simulating a fare for one subscriber (direct invoke only; goes through the real paywall gate, dedup and Resend):

```bash
aws lambda invoke --function-name flight-parser --region us-east-1 out.json --payload \
  '{"origin":"TPE","destination":"TYO","route":"TPE-TYO","simulate":{"email":"<you>","price_twd":5000}}'
# add "now":"YYYY-MM-DDTHH:MM:SSZ" to evaluate the gate at another moment (never writes)
```

Dedup knobs on `flight-fare-notification`: `NOTIFY_FLOOR_HOURS=24`, `REALERT_PCT=20`, `REALERT_ABS_TWD=2000`.
