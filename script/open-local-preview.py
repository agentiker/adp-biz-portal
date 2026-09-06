"""Open a short-lived, signed login URL for this local-only preview."""
import argparse
import hashlib
import hmac
from pathlib import Path
import time
from urllib.parse import urlencode, urlparse
import webbrowser

from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument("--print-url", action="store_true")
args = parser.parse_args()
settings = dotenv_values(Path(__file__).resolve().parents[1] / "server" / ".env")
base_url = settings.get("SERVICE_API_URL", "").rstrip("/")
if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit("This helper is restricted to localhost.")
secret = settings.get("CUSTOMER_ACCOUNT_SECRET_KEY")
if not secret:
    raise SystemExit("CUSTOMER_ACCOUNT_SECRET_KEY is missing.")
customer_id = "local-preview"
name = "Local Preview"
timestamp = int(time.time())
message = f"{customer_id}{name}{timestamp}"
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
url = base_url + "/account/customer?" + urlencode({
    "CustomerId": customer_id,
    "Name": name,
    "ExtraInfo": "",
    "Timestamp": timestamp,
    "Code": signature,
})
if args.print_url:
    print(url)
else:
    if not webbrowser.open(url):
        raise SystemExit("Could not open the browser; use --print-url and open within 60 seconds.")
    print("Opened local preview with a short-lived signed login link.")
