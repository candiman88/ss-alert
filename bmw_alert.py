import os, json, smtplib, requests
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# ---------- SETTINGS ----------
URL = "https://www.ss.com/lv/transport/cars/bmw/3-series/filter/"
# (option text, which dropdown containing it: 0 = first, 1 = second)
FILTERS = [
    ("1992", 0),        # Gads from
    ("1997", 1),        # Gads to
    ("2.0", 0),         # Tilpums from
    ("Benzīns", 0),     # Dzinējs
    ("Manuāl", 0),      # Ātrumkārba
    ("3. sērija", 0),   # Modelis
]
GMAIL = os.environ["GMAIL_ADDRESS"]
APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# ------------------------------

SEEN_FILE = Path(__file__).with_name("seen_bmw.json")


def clean(text):
    return " ".join(text.split())


def pick(select, text):
    opts = select.find_all("option")
    for o in opts:
        if clean(o.get_text()) == text:
            return o
    for o in opts:
        if clean(o.get_text()).startswith(text):
            return o
    return None


def get_ads():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    r = s.get(URL, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    form = None
    for f in soup.find_all("form"):
        sels = f.find_all("select")
        if all(any(pick(x, t) for x in sels) for t, _ in FILTERS):
            form = f
            break
    if form is None:
        raise RuntimeError("Filter form not found")

    selects = form.find_all("select")
    chosen = {}
    for text, nth in FILTERS:
        matching = [x for x in selects if pick(x, text)]
        if len(matching) <= nth:
            raise RuntimeError(f"Filter option not found: {text}")
        chosen[id(matching[nth])] = pick(matching[nth], text)
        print("Filter:", text)

    data = {}
    for el in form.find_all(["input", "select"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "select":
            o = chosen.get(id(el))
            if o is None:
                opts = el.find_all("option")
                o = next((x for x in opts if x.has_attr("selected")),
                         opts[0] if opts else None)
            data[name] = o.get("value", clean(o.get_text())) if o else ""
        elif el.get("type") in ("checkbox", "radio"):
            if el.has_attr("checked"):
                data[name] = el.get("value", "on")
        elif el.get("type") not in ("submit", "button"):
            data[name] = el.get("value", "")

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
        tds = tr.find_all("td", recursive=False)
        cells = [clean(td.get_text()) for td in tds]
        ads.append({
            "id": tr["id"],
            "title": clean(a.get_text()),
            "url": "https://www.ss.com" + a["href"],
            "price_txt": cells[-1],
            "details": " | ".join(c for c in cells[3:] if c),
        })
    if not ads:
        raise RuntimeError("No ads parsed, page layout or filter problem")
    return ads


def send_mail(ad):
    msg = EmailMessage()
    msg["Subject"] = f"New BMW ad: {ad['title']} - {ad['price_txt']}"
    msg["From"] = GMAIL
    msg["To"] = GMAIL
    msg.set_content(f"{ad['title']}\n{ad['details']}\n\n{ad['url']}")
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
