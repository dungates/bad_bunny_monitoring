#!/usr/bin/env python3
"""Monitor the Bad Bunny Tokyo concert page for changes and send email alerts."""

import hashlib
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

URL = "https://depuertoricopalmundo.com/"
STATE_FILE = SCRIPT_DIR / "last_state.json"
LOG_FILE = SCRIPT_DIR / "monitor.log"

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
NOTIFY_EMAILS = [e.strip() for e in os.getenv("NOTIFY_EMAILS", "").split(",") if e.strip()]


def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def parse_tokyo_info(html):
    """Parse HTML and extract the Tokyo concert section."""
    soup = BeautifulSoup(html, "html.parser")
    tokyo_div = soup.find("div", id="japan_march_2026")

    if not tokyo_div:
        # Fallback: search for any dateWrapper containing "Tokyo"
        for div in soup.find_all("div", class_="dateWrapper"):
            if "Tokyo" in div.get_text():
                tokyo_div = div
                break

    if not tokyo_div:
        # Last resort: look for any element with japan in the id
        for div in soup.find_all("div", class_="dateWrapper"):
            div_id = div.get("id", "")
            if "japan" in div_id.lower():
                tokyo_div = div
                break

    if not tokyo_div:
        raise ValueError("Could not find Tokyo concert section on the page")

    # Extract the key fields
    date_el = tokyo_div.find("p", class_="date")
    city_els = tokyo_div.find_all("p", class_="city")
    venue_el = tokyo_div.find("p", class_="venue")
    button_el = tokyo_div.find("a", class_="topBut")

    info = {
        "element_id": tokyo_div.get("id", ""),
        "date": date_el.get_text(strip=True) if date_el else "",
        "city": ", ".join(el.get_text(strip=True).rstrip(",") for el in city_els),
        "venue": venue_el.get_text(strip=True) if venue_el else "",
        "button_text": button_el.get_text(strip=True) if button_el else "",
        "button_link": button_el.get("href", "") if button_el else "",
        "full_text": tokyo_div.get_text(separator=" ", strip=True),
    }

    return info


def fetch_tokyo_info():
    """Fetch the page and extract the Tokyo concert section."""
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    return parse_tokyo_info(resp.text)


def load_last_state():
    """Load the last saved state from disk."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def save_state(info):
    """Save the current state to disk."""
    with open(STATE_FILE, "w") as f:
        json.dump(info, f, indent=2)


def send_email(old_info, new_info):
    """Send an email alert about the change."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log("ERROR: Gmail credentials not configured in .env file")
        sys.exit(1)

    changes = []
    for key in ["date", "city", "venue", "button_text", "button_link"]:
        old_val = (old_info or {}).get(key, "(none)")
        new_val = new_info.get(key, "(none)")
        if old_val != new_val:
            changes.append(f"  {key}:\n    OLD: {old_val}\n    NEW: {new_val}")

    changes_text = "\n\n".join(changes) if changes else "  (see full text comparison below)"

    body = f"""The Bad Bunny Tokyo concert info has CHANGED!

Website: {URL}

CHANGES DETECTED:
{changes_text}

CURRENT INFO:
  Date: {new_info['date']}
  City: {new_info['city']}
  Venue: {new_info['venue']}
  Button: {new_info['button_text']}
  Link: {new_info['button_link']}

PREVIOUS INFO:
  Date: {(old_info or {}).get('date', '(first check)')}
  City: {(old_info or {}).get('city', '(first check)')}
  Venue: {(old_info or {}).get('venue', '(first check)')}
  Button: {(old_info or {}).get('button_text', '(first check)')}
  Link: {(old_info or {}).get('button_link', '(first check)')}

Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    msg = MIMEText(body)
    msg["Subject"] = "🚨 Bad Bunny Tokyo Concert Info Changed!"
    recipients = NOTIFY_EMAILS if NOTIFY_EMAILS else [GMAIL_ADDRESS]
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD.replace(" ", ""))
        server.send_message(msg)

    log("Alert email sent successfully!")


MONITORED_FIELDS = ["date", "city", "venue", "button_text", "button_link"]


def detect_changes(old_info, new_info):
    """Compare two info dicts and return a dict of changed fields.

    Returns {field: (old_value, new_value)} for each changed field,
    or an empty dict if nothing changed.
    """
    changes = {}
    for key in MONITORED_FIELDS:
        old_val = (old_info or {}).get(key)
        new_val = new_info.get(key)
        if old_val != new_val:
            changes[key] = (old_val, new_val)
    return changes


def main():
    log("Checking Tokyo concert info...")

    try:
        current_info = fetch_tokyo_info()
    except Exception as e:
        log(f"ERROR fetching page: {e}")
        sys.exit(1)

    last_info = load_last_state()

    if last_info is None:
        # First run — save baseline
        save_state(current_info)
        log(f"First run — saved baseline: date={current_info['date']}, "
            f"venue={current_info['venue']}, button={current_info['button_text']}")
        return

    changes = detect_changes(last_info, current_info)

    if changes:
        for key, (old_val, new_val) in changes.items():
            log(f"CHANGE in {key}: '{old_val}' -> '{new_val}'")
        log("Changes detected! Sending email alert...")
        try:
            send_email(last_info, current_info)
        except Exception as e:
            log(f"ERROR sending email: {e}")
        save_state(current_info)
    else:
        log("No changes detected.")


def test_alert():
    """Send a fake alert simulating Tokyo tickets going on sale."""
    log("TESTING: Simulating Tokyo concert update...")

    old_info = {
        "element_id": "japan_march_2026",
        "date": "March 2026",
        "city": "Tokyo, Japan",
        "venue": "TBD",
        "button_text": "MORE INFORMATION COMING SOON",
        "button_link": "#",
        "full_text": "March 2026 Tokyo, Japan TBD MORE INFORMATION COMING SOON",
    }

    new_info = {
        "element_id": "japan_march_14_2026",
        "date": "March 14 2026",
        "city": "Tokyo, Japan",
        "venue": "Tokyo Dome",
        "button_text": "TICKETS ON SALE NOW",
        "button_link": "https://www.ticketmaster.co.jp/event/badbunny",
        "full_text": "March 14 2026 Tokyo, Japan Tokyo Dome TICKETS ON SALE NOW",
    }

    changes = detect_changes(old_info, new_info)
    for key, (old_val, new_val) in changes.items():
        log(f"SIMULATED CHANGE in {key}: '{old_val}' -> '{new_val}'")

    send_email(old_info, new_info)
    log("Test alert sent! Check your inbox.")


if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        test_alert()
    else:
        main()
