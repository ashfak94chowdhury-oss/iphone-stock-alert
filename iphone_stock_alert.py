"""
iPhone Stock Alert for apple.ae
-------------------------------
Checks Apple UAE every few minutes and alerts you (sound + popup)
when your iPhone is available for pickup at a UAE Apple Store
or for delivery.

Default: iPhone 18 Pro Max 256GB Burgundy.
Needs only Python - nothing to install.

How to run (Windows, in cmd):
    python iphone_stock_alert.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

# ================== YOUR SETTINGS ==================
# Product page of the exact model on apple.ae. Pick the model, size and colour on
# apple.ae, then copy the link from the address bar and paste it here.
PRODUCT_URL = "https://www.apple.com/ae/shop/buy-iphone/iphone-18-pro/6.9-inch-display-256gb-burgundy"

# Apple's part number for this exact model (looks like "MXXXXAE/A").
# Leave it empty ("") and the script will try to find it from PRODUCT_URL.
PART_NUMBER = ""

# Where to look for pickup stores (an emirate or city name).
LOCATION = "Abu Dhabi"

# Only alert for these stores. Empty list [] = alert for ANY UAE store.
# Example: ["Yas Mall", "Al Maryah Island"]
STORES_I_WANT = []

# Also alert if it can be ordered for home delivery?
ALERT_ON_DELIVERY = True

CHECK_EVERY_MINUTES = 3  # please don't go lower; Apple may block you

# Phone notifications with the free "ntfy" app. Pick a long, secret topic name,
# e.g. "asfak-iphone-x7k29q", and subscribe to the same name in the ntfy app.
# (On GitHub this comes from a secret instead; see the guide.)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# On GitHub we check once and stop (GitHub repeats it on a schedule).
RUN_ONCE = os.environ.get("RUN_ONCE") == "1"
# ===================================================

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "en-AE,en;q=0.9",
}


def log(text):
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200].replace("\n", " ")
        raise RuntimeError(f"HTTP {e.code} - {body!r}") from None


# ---------- Step 1: find the part number ----------
def find_part_number(url):
    """Looks inside the apple.ae page for Apple part numbers like MXXXXAE/A."""
    html = get(url)
    found = re.findall(r'"partNumber"\s*:\s*"([A-Z0-9]{4,6}AE/A)"', html)
    if not found:
        found = re.findall(r"\b(M[A-Z0-9]{3,5}AE/A)\b", html)
    found = list(dict.fromkeys(found))  # remove duplicates, keep order
    m_parts = re.findall(r"\b(M[A-Z0-9]{3,5}AE/A)\b", html)
    log(f"Part numbers on page: {found[:10]} | M-style: {list(dict.fromkeys(m_parts))[:10]}")
    return found


# ---------- Step 2: check stock ----------
SHOP = "https://www.apple.com/ae/shop"
WORKING_WAY = None  # remembers which way of asking Apple worked


def ways_to_ask(part):
    """Different ways of asking Apple for stock. We try them in order."""
    q = urllib.parse.urlencode
    return [
        ("A", f"{SHOP}/fulfillment-messages?" + q({"pl": "true", "mts.0": "regular",
                                                    "parts.0": part, "location": LOCATION})),
        ("B", f"{SHOP}/fulfillment-messages?" + q({"fae": "true", "pl": "true", "mts.0": "regular",
                                                    "mts.1": "compact", "parts.0": part,
                                                    "searchNearby": "true"})),
        ("C", f"{SHOP}/fulfillment-messages?" + q({"pl": "true", "mts.0": "regular",
                                                    "parts.0": part})),
        ("D", f"{SHOP}/retail/pickup-message?" + q({"parts.0": part, "location": LOCATION})),
    ]


def ask_apple(part):
    global WORKING_WAY
    errors = []
    for name, url in ways_to_ask(part):
        if WORKING_WAY and name != WORKING_WAY:
            continue
        try:
            data = json.loads(get(url))
            if WORKING_WAY != name:
                log(f"Way {name} worked. Reply sections: {list(data.get('body', data).keys())[:8]}")
            WORKING_WAY = name
            return data
        except Exception as e:
            errors.append(f"way {name}: {e}")
    raise RuntimeError(" | ".join(errors))


def check_stock(part):
    """Asks Apple's store for pickup + delivery availability of one part."""
    data = ask_apple(part)
    content = data.get("body", {}).get("content", data.get("body", {}))

    # Pickup at stores
    available_stores = []
    stores = content.get("pickupMessage", {}).get("stores") or content.get("stores") or []
    log(f"Apple listed {len(stores)} store(s).")
    for store in stores:
        info = store.get("partsAvailability", {}).get(part, {})
        if info.get("pickupDisplay") == "available":
            available_stores.append(store.get("storeName", "Unknown store"))
    if STORES_I_WANT:
        available_stores = [s for s in available_stores
                            if any(w.lower() in s.lower() for w in STORES_I_WANT)]

    # Home delivery
    delivery_text = None
    delivery = content.get("deliveryMessage", {}).get(part, {})
    regular = delivery.get("regular", {})
    if regular.get("isBuyable"):
        options = regular.get("deliveryOptions") or [{}]
        delivery_text = options[0].get("date") or "available"

    return available_stores, delivery_text


# ---------- Step 3: alert ----------
def send_phone_notification(message):
    """Sends a push notification to your phone through the free ntfy app."""
    if not NTFY_TOPIC:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": "iPhone 18 Pro Max in stock!",
                     "Priority": "urgent",
                     "Click": PRODUCT_URL},
        )
        urllib.request.urlopen(req, timeout=30)
        log("Phone notification sent.")
    except Exception as e:
        log(f"Could not send phone notification: {e}")


def alert(message):
    log("*** " + message + " ***")
    send_phone_notification(message)
    if RUN_ONCE:  # running on GitHub: no screen, no sound
        return
    if sys.platform == "win32":
        import ctypes
        import winsound
        for _ in range(5):
            winsound.Beep(1200, 400)
        webbrowser.open(PRODUCT_URL)
        ctypes.windll.user32.MessageBoxW(0, message, "iPhone in stock!", 0x40 | 0x1000)
    else:
        print("\a")
        webbrowser.open(PRODUCT_URL)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    part = PART_NUMBER.strip()
    if not part:
        log("Finding the part number from the apple.ae page...")
        try:
            parts = find_part_number(PRODUCT_URL)
        except Exception as e:
            log(f"Could not open the product page: {e}")
            parts = []
        if len(parts) == 1:
            part = parts[0]
        else:
            if parts:
                log("Found several part numbers on the page: " + ", ".join(parts))
            else:
                log("Could not find the part number on the page.")
            log("Please type PART_NUMBER at the top of this file and run again.")
            return

    log(f"Watching part {part} near {LOCATION}. Checking every {CHECK_EVERY_MINUTES} min.")
    log("Leave this window open. Press Ctrl+C to stop.")

    while True:
        try:
            stores, delivery = check_stock(part)
            if stores:
                alert("Available for PICKUP at: " + ", ".join(stores))
                break
            if ALERT_ON_DELIVERY and delivery:
                alert(f"Available to ORDER for delivery ({delivery})")
                break
            log("Not available yet.")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"Check failed ({e}). Will try again.")
        if RUN_ONCE:
            break
        time.sleep(CHECK_EVERY_MINUTES * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
