import os, json, smtplib, requests
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# ---------- SETTINGS ----------
URL = "https://www.ss.com/lv/electronics/computers/game-consoles/filter/"
CONSOLE = "PlayStation 5"             # value picked in the "Konsole" dropdown
GMAIL = os.environ["GMAIL_ADDRESS"]
APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# ------------------------------

SEEN_FILE = Path(__file__).with_name("seen.json")


def clean(text):
    return " ".join(text.split())


def get_ads():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    r = s.get(URL, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # find the filter form (the one containing the console dropdown)
    form = None
    for f in soup.find_all("form"):
        if any(o.get_text(strip=True) == CONSOLE for o in f.find_all("option")):
            form = f
            break
    if form is None:
        raise RuntimeError("Filter form not found")

    # build the form data, with Console set to PlayStation 5
    data = {}
    for el in form.find_all(["input", "select"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "select":
            opts = el.find_all("option")
            chosen = next((o for o in opts if o.get_text(strip=True) == CONSOLE), None)
            if chosen is None:
                chosen = next((o for o in opts if o.has_attr("selected")),
                              opts[0] if opts else None)
            data[name] = (chosen.get("value", chosen.get_text(strip=True))
                          if chosen else "")
        elif el.get("type") in ("checkbox", "radio"):
            if el.has_attr("checked"):
                data[name] = el.get("value", "on")
        elif el.get("type") not in ("submit", "button"):
            data[name] = el.get("value", "")

    # submit the form like the "Meklēt" button does
    action = urljoin(URL, form.get("action") or URL)
    if form.get("method", "get").lower() == "post":
        r = s.post(action, data=data, timeout=20)
    else:
        r = s.get(action, params=data, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    ads = []
    for tr in soup.select('tr[id^="tr_"]'):
        a = tr.select_one("a.am")
        if not a or tr["id"] == "tr_bnr":
            continue
        if CONSOLE not in tr.get_text():   # safety net if the filter didn't apply
            continue
        ads.append({
            "id": tr["id"],
            "title": clean(a.get_text()),
            "url": "https://www.ss.com" + a["href"],
            "price_txt": clean(tr.find_all("td", recursive=False)[-1].get_text()),
        })
    if not ads:
        raise RuntimeError("No ads parsed, page layout or filter problem")
    return ads


def send_mail(ad):
    msg = EmailMessage()
    msg["Subject"] = f"New PS5 ad: {ad['title']} - {ad['price_txt']}"
    msg["From"] = GMAIL
    msg["To"] = GMAIL
    msg.set_content(f"{ad['title']}\n{ad['price_txt']}\n\n{ad['url']}")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL, APP_PASSWORD)
            s.send_message(msg)
    except (smtplib.SMTPServerDisconnected, OSError):
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(GMAIL, APP_PASSWORD)
            s.send_message(msg)


def main():
    first_run = not SEEN_FILE.exists()
    seen = set(json.loads(SEEN_FILE.read_text())) if not first_run else set()
    ads = get_ads()
    print(f"{len(ads)} ads found")

    if not first_run:
        for ad in ads:
            if ad["id"] not in seen:
                send_mail(ad)
                seen.add(ad["id"])
                SEEN_FILE.write_text(json.dumps(list(seen)))
                print("Sent:", ad["title"])

    seen |= {ad["id"] for ad in ads}
    SEEN_FILE.write_text(json.dumps(list(seen)[-2000:]))


if __name__ == "__main__":
    main()
