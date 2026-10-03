# AWS backend (M1 — free price-drop notifier)

Source of the Lambdas deployed in **us-east-1**. Each function is a single `index.py`
(`index.handler`, python3.12, boto3 + stdlib only, no layer, no VPC).

| Function | Deploy | Trigger |
|---|---|---|
| `flight-save-subscription` | CloudFormation stack (inline `Code.ZipFile`) | API GW `POST /subscribe` |
| `flight-list-subscriptions` | CloudFormation stack (inline `Code.ZipFile`) | API GW `GET /subscriptions?email=` |
| `flight-parser-wrapper` | `s3://flight-config-<ACCOUNT_ID>/lambda/wrapper.zip` | EventBridge `flight-price-check` (`rate(30 minutes)`) |
| `flight-parser` | `s3://flight-config-<ACCOUNT_ID>/lambda/parser.zip` | async invoke from the wrapper, one per route |
| `flight-fare-notification` | `s3://flight-config-<ACCOUNT_ID>/lambda/fare-notification.zip` | SQS `flight-fare-queue` (batch 5, ReportBatchItemFailures) |
| `flight-git-push` | CloudFormation stack (inline) | manual — deploy helper that commits to this repo via the GitHub API |

Data: DynamoDB `subscriptions` (email / route) and `notification_history` (pk = `email#route`, sent_at ISO-8601).
Secrets (Secrets Manager): `flight/travelpayouts` `{token}`, `flight/resend` `{api_key, from, test_to}`.
IAM: all runtime Lambdas use `flight-lambda-role` with the inline policy in `iam/flight-data-policy.json`.

Dedup knobs on `flight-fare-notification`: `NOTIFY_FLOOR_HOURS=24`, `REALERT_PCT=20`, `REALERT_ABS_TWD=2000`.

M1 has **no payment guard** — a subscription row means "eligible for alerts" (`subscription_status` arrives in M2).

Redeploy a function after editing it: zip its `index.py` (`zip -j x.zip index.py`), upload to the S3 key above,
check the S3 ETag equals the local md5, then `aws lambda update-function-code --s3-bucket … --s3-key … --region us-east-1`.
