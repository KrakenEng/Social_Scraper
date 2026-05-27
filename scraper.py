import csv
import time
import requests
from datetime import datetime, timezone, timedelta
from html import unescape
import re

BASE_URL = "https://truthsocial.com"
OUTPUT_FILE = "truth_posts.csv"
PROFILE = "realDonaldTrump"
CUTOFF_DAYS = 30
PAGE_LIMIT = 20
REQUEST_DELAY = 1.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def get_guest_token(session):
    """Register a guest session and return bearer token."""
    resp = session.post(f"{BASE_URL}/api/v1/pepe/registrations", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_account_id(session, username):
    resp = session.get(
        f"{BASE_URL}/api/v1/accounts/lookup",
        params={"acct": username},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def strip_html(html_text):
    text = unescape(html_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def fetch_statuses(session, account_id, max_id=None, since_id=None):
    params = {
        "exclude_replies": "true",
        "only_replies": "false",
        "with_muted": "true",
        "limit": PAGE_LIMIT,
    }
    if max_id:
        params["max_id"] = max_id
    if since_id:
        params["since_id"] = since_id
    resp = session.get(
        f"{BASE_URL}/api/v1/accounts/{account_id}/statuses",
        params=params,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def load_existing(filename):
    """Return (set of existing IDs, newest post ID or None)."""
    rows = []
    try:
        with open(filename, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return set(), None
    ids = {r["id"] for r in rows if r.get("id")}
    newest_id = max(ids, key=lambda x: int(x)) if ids else None
    return ids, newest_id


def scrape(username, cutoff_days):
    existing_ids, since_id = load_existing(OUTPUT_FILE)
    if since_id:
        print(f"Resuming from post ID {since_id} ({len(existing_ids)} posts already collected).")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        print(f"No existing data — fetching last {cutoff_days} days.")
    posts = []

    session = requests.Session()

    print("Getting guest token...")
    token = get_guest_token(session)
    session.headers.update({"Authorization": f"Bearer {token}"})

    print(f"Looking up account: @{username}")
    account_id = get_account_id(session, username)
    print(f"Account ID: {account_id}")

    max_id = None
    page = 0

    while True:
        page += 1
        print(f"  Fetching page {page} (max_id={max_id})...")
        statuses = fetch_statuses(session, account_id, max_id=max_id, since_id=since_id)

        if not statuses:
            print("Caught up — no more new posts.")
            break

        hit_cutoff = False
        for s in statuses:
            if not since_id:
                created = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
                if created < cutoff:
                    hit_cutoff = True
                    break

            text = strip_html(s.get("content", ""))
            if not text and s.get("reblog"):
                text = strip_html(s["reblog"].get("content", ""))

            posts.append({
                "id": s["id"],
                "created_at": s["created_at"],
                "url": s.get("url", ""),
                "text": text.replace("\n", " "),
                "reblog": "yes" if s.get("reblog") else "no",
            })

        print(f"    -> {len(posts)} posts collected so far")

        if hit_cutoff:
            print(f"Reached {cutoff_days}-day cutoff.")
            break

        max_id = statuses[-1]["id"]
        time.sleep(REQUEST_DELAY)

    return posts


def save_csv(new_posts, filename):
    if not new_posts:
        print("No new posts to save.")
        return

    # Load existing rows, merge, deduplicate, re-sort
    existing = []
    try:
        with open(filename, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    except FileNotFoundError:
        pass

    seen = set()
    merged = []
    for row in existing + new_posts:
        rid = row["id"]
        if rid not in seen:
            seen.add(rid)
            merged.append(row)

    merged.sort(key=lambda p: p["created_at"], reverse=True)

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["created_at", "id", "url", "reblog", "text"])
        writer.writeheader()
        writer.writerows(merged)

    print(f"Saved {len(merged)} total posts ({len(new_posts)} new) to {filename}")


if __name__ == "__main__":
    posts = scrape(PROFILE, CUTOFF_DAYS)
    save_csv(posts, OUTPUT_FILE)
