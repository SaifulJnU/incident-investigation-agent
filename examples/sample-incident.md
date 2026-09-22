# Checkout errors after the payments deploy

Started: 2026-09-22 14:02 UTC
Service: checkout-api
Symptom: HTTP 500 rate climbed from under 0.1% to about 8% on POST /checkout.
Scope: Web and mobile. Other APIs look normal.
Recent change: payments-api 1.42.0 deployed at 14:02 UTC.
What we know: no database failover was announced. On-call has not rolled back yet.
Ask: find the leading cause, the safest immediate mitigation, and the next checks.
