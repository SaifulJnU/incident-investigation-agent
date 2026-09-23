import os

os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("DEV_AUTH_SECRET", "test-dev-secret-value-32bytes-min")
os.environ.setdefault(
    "DEV_USERS",
    "oncall|On-call engineer|checkout-api,payments-api|oncall-password;"
    "platform|Platform owner|*|platform-password",
)
