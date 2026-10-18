# Бот поиска заказов: следит за Reddit и шлёт подходящие посты в Telegram.
import os, json, re, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]

# ---- ГДЕ ИСКАТЬ (можно дописывать свои строки) ----
SUBS = ["SunoAI", "udiomusic", "WeAreTheMusicMakers", "musicians",
        "songwriters", "makingmusic", "HireAMusician", "forhire"]
SEARCH = ["need guitarist", "session guitarist", "real guitar suno",
          "live guitar ai song", "hire guitar player"]

# ---- ЧТО ИСКАТЬ ----
STRONG = ["session guitar", "need a guitarist", "looking for a guitarist",
          "hire a guitarist", "real guitarist", "live guitar", "real guitar",
          "human guitarist", "humanize", "re-record the guitar",
          "replace the guitar", "guitar player wanted",
          "нужен гитарист", "ищу гитариста", "живая гитара", "живую гитару"]
GUITAR = ["guitar", "гитар"]
INTENT = ["hire", "looking for", "need", "paid", "replace", "re-record",
          "rerecord", "human", "real", "live", "collab", "нужн", "ищу", "заплачу"]

SEEN_FILE = "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (guitar-leads-bot by chasb1974)"}
A = "{http://www.w3.org/2005/Atom}"

def feeds():
    for s in SUBS:
        yield f"r/{s}", f"https://www.reddit.com/r/{s}/new/.rss?limit=50"
    for q in SEARCH:
        yield f"поиск «{q}»", ("https://www.reddit.com/search.rss?sort=new&q="
                               + urllib.parse.quote(q))

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def match(text):
    t = text.lower()
    if any(p in t for p in STRONG):
        return True
    return any(g in t for g in GUITAR) and any(i in t for i in INTENT)

def clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()

def send(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
                           data, timeout=30)

def main():
    try:
        st = json.load(open(SEEN_FILE, encoding="utf-8"))
    except Exception:
        st = {"ids": [], "err_day": ""}
    first = not st["ids"]
    seen = set(st["ids"])
    found, ok, fails = [], 0, 0

    for name, url in feeds():
        try:
            root = ET.fromstring(get(url))
            ok += 1
        except Exception as e:
            fails += 1
            print("Ошибка", name, e)
            continue
        for en in root.findall(A + "entry"):
            pid = en.findtext(A + "id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            title = en.findtext(A + "title") or ""
            body = clean(en.findtext(A + "content"))
            link = en.find(A + "link").get("href")
            if match(title + " " + body):
                found.append((name, title, body[:300], link))
        time.sleep(2)

    if first:
        send(f"✅ Бот запущен. Слежу за {ok} лентами. Новые посты буду присылать сюда.")
    else:
        for name, title, body, link in found[:15]:
            send(f"🎸 {name}\n{title}\n\n{body}\n\n{link}")

    today = time.strftime("%Y-%m-%d")
    if ok == 0 and st.get("err_day") != today:
        send("⚠️ Reddit не отвечает боту (возможна блокировка). Напиши Claude.")
        st["err_day"] = today

    st["ids"] = list(seen)[-3000:]
    json.dump(st, open(SEEN_FILE, "w", encoding="utf-8"))
    print(f"Лент: {ok}, ошибок: {fails}, найдено: {len(found)}")

main()
