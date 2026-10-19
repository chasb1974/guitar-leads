# Бот поиска заказов: следит за Reddit и шлёт подходящие посты в Telegram.
import os, json, re, time, imaplib, email, urllib.request, urllib.parse, urllib.error, xml.etree.ElementTree as ET
from email.header import decode_header, make_header

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]

# ---- ГДЕ ИСКАТЬ (можно дописывать свои строки) ----
SUBS = ["SunoAI", "udiomusic", "WeAreTheMusicMakers", "musicians",
        "songwriters", "makingmusic", "HireAMusician", "forhire"]
SEARCH = ["need guitarist", "session guitarist", "real guitar suno",
          "live guitar ai song", "hire guitar player"]

# ---- ЧТО ИСКАТЬ ----
# Берём только посты, где кто-то ИЩЕТ гитариста (за деньги / на заказ)
HIRE = ["session guitar", "need a guitarist", "need a guitar player", "looking for a guitarist",
        "looking for a guitar player", "hire a guitarist", "hire a guitar", "guitarist wanted",
        "guitar player wanted", "re-record the guitar", "replace the guitar", "replace my guitar",
        "real guitarist", "human guitarist", "need guitar", "guitar parts", "guitar tracks",
        "нужен гитарист", "ищу гитариста", "нужна гитара", "живую гитару", "живая гитара"]
GUITAR = ["guitar", "гитар"]
# Признаки оплаты (целые слова, чтобы "rate" не ловилось в "generated")
MONEY_RE = re.compile(r"\$\s?\d|\d\s?\$|\bpaid\b|\bpay\b|\bpaying\b|\bbudget\b|\busd\b|€|£|"
                      r"\bfee\b|\brates?\b|\bcompensat|\bhire\b|\bhiring\b|"
                      r"оплат|заплач|бюджет|гонорар|за деньги|платн|₽|\bруб|тенге|\bтг\b")
# Мусор: сами предлагают услуги, спрашивают совета, показывают своё
SKIP = ["for hire", "[for hire]", "available for", "my services", "i offer", "i'm offering",
        "i am a guitarist", "i'm a guitarist", "i'm a session", "feedback", "how do i",
        "how to ", "tutorial", "review", "check out my", "my new song", "my new track",
        "rate my", "free download", "plugin", "preset", "unpaid", "no budget",
        "rev share", "revenue share", "for exposure", "collab", "[offer]",
        "ищу группу", "ищу коллектив", "преподавател", "педагог", "бесплатно", "без оплаты"]

# ---- TELEGRAM-КАНАЛЫ (публичные, читаем веб-версию t.me/s/...) ----
TG_CHANNELS = ["musiclance", "musician_msk", "spbmuzpoisk", "bandlinksoundcheck"]
# В каналах нужна именно запись/сессия, а не "ищем гитариста в группу"
TG_WORK = ["запис", "сессион", "студи", "трек", "партию", "партии", "удалён", "удален",
           "онлайн", "дистанц", "аранжиров", "session", "record", "remote"]

SEEN_FILE = "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (guitar-leads-bot by chasb1974)"}
A = "{http://www.w3.org/2005/Atom}"

def feeds():
    # Всё в 2 запроса, иначе Reddit отвечает 429 (слишком много запросов)
    yield "subs", "Reddit", ("https://www.reddit.com/r/" + "+".join(SUBS)
                             + "/new/.rss?limit=100")
    q = " OR ".join(f'"{x}"' for x in SEARCH)
    yield "search", "поиск Reddit", ("https://www.reddit.com/search.rss?sort=new&limit=100&q="
                                     + urllib.parse.quote(q))

def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(30)

def match(text):
    t = text.lower()
    if any(x in t for x in SKIP):
        return False
    if not any(g in t for g in GUITAR):
        return False
    if not any(p in t for p in HIRE):
        return False
    return bool(MONEY_RE.search(t))

def tg_match(text):
    t = text.lower()
    if any(x in t for x in SKIP):
        return False
    return (any(g in t for g in GUITAR) and any(w in t for w in TG_WORK)
            and bool(MONEY_RE.search(t)))

def tg_posts(ch):
    """Последние посты публичного канала: (id, текст, ссылка)."""
    html = get("https://t.me/s/" + ch).decode("utf-8", "replace")
    out = []
    for part in html.split('data-post="')[1:]:
        post = part[:part.index('"')]
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', part, re.S)
        if m:
            txt = clean(m.group(1).replace("<br/>", " ").replace("<br>", " "))
            out.append(("tg:" + post, txt, "https://t.me/" + post))
    return out

def clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()

def ru(text):
    """Перевод на русский через бесплатный Google Translate; при сбое возвращает пусто."""
    try:
        text = text[:1500]
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ru&dt=t&q="
               + urllib.parse.quote(text))
        r = json.loads(urllib.request.urlopen(url, timeout=20).read().decode("utf-8"))
        return "".join(p[0] for p in r[0] if p[0]).strip()
    except Exception as e:
        print("Ошибка перевода", e)
        return ""

def send(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
                           data, timeout=30)

# ---- ПОЧТА: письма от площадок ----
MAIL_USER = os.environ.get("GMAIL_USER", "")
MAIL_PASS = os.environ.get("GMAIL_PASS", "").replace(" ", "")
MAIL_SITES = {"airgigs.com": "AirGigs", "fiverr.com": "Fiverr"}

def hdr(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""

def body_text(msg):
    part = None
    for p in msg.walk():
        if p.get_content_type() == "text/plain":
            part = p
            break
    if part is None:
        for p in msg.walk():
            if p.get_content_type() == "text/html":
                part = p
                break
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    txt = raw.decode(part.get_content_charset() or "utf-8", "replace")
    return clean(txt)

def check_mail(seen, quiet):
    """Возвращает список (сайт, тема, текст) новых писем от площадок."""
    out = []
    if not MAIL_USER or not MAIL_PASS:
        return out, False
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(MAIL_USER, MAIL_PASS)
    m.select("INBOX", readonly=True)
    q = "from:(" + " OR ".join(MAIL_SITES) + ") newer_than:2d"
    typ, data = m.search(None, "X-GM-RAW", '"%s"' % q)
    for num in (data[0].split() if data and data[0] else [])[-30:]:
        typ, d = m.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(d[0][1])
        mid = "mail:" + (msg.get("Message-ID") or num.decode())
        if mid in seen:
            continue
        seen.add(mid)
        frm = (msg.get("From") or "").lower()
        site = next((n for k, n in MAIL_SITES.items() if k in frm), "Площадка")
        if not quiet:
            out.append((site, hdr(msg.get("Subject")), body_text(msg)[:300]))
    m.logout()
    return out, True

def main():
    try:
        st = json.load(open(SEEN_FILE, encoding="utf-8"))
    except Exception:
        st = {"ids": [], "err_day": ""}
    first = not st["ids"]
    known = set(st.get("feeds", []))
    seen = set(st["ids"])
    found, ok, fails = [], 0, 0

    for key, name, url in feeds():
        try:
            root = ET.fromstring(get(url))
            ok += 1
        except Exception as e:
            fails += 1
            print("Ошибка", name, e)
            continue
        quiet = key not in known  # новую ленту в первый раз только запоминаем
        known.add(key)
        for en in root.findall(A + "entry"):
            pid = en.findtext(A + "id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            title = en.findtext(A + "title") or ""
            body = clean(en.findtext(A + "content"))
            link = en.find(A + "link").get("href")
            if not quiet and match(title + " " + body):
                found.append((name, title, body[:300], link))
        time.sleep(10)

    tg_ok = 0
    for ch in TG_CHANNELS:
        try:
            posts = tg_posts(ch)
            tg_ok += 1
        except Exception as e:
            print("Ошибка Telegram", ch, e)
            continue
        quiet = ("tg:" + ch) not in known
        known.add("tg:" + ch)
        for pid, txt, link in posts:
            if pid in seen:
                continue
            seen.add(pid)
            if not quiet and tg_match(txt):
                found.append(("Telegram @" + ch, "", txt[:500], link))
        print("Канал", ch, "постов:", len(posts))
        time.sleep(3)

    mails = []
    try:
        mquiet = "mail" not in known
        mails, mail_on = check_mail(seen, mquiet)
        if mail_on:
            known.add("mail")
            if mquiet:
                send("📬 Почта подключена. Новые письма от AirGigs и Fiverr буду присылать сюда.")
    except Exception as e:
        print("Ошибка почты", e)
        if st.get("mail_err_day") != time.strftime("%Y-%m-%d"):
            send("⚠️ Не получается проверить почту Gmail. Напиши Claude.")
            st["mail_err_day"] = time.strftime("%Y-%m-%d")
    for site, subj, txt in mails[:10]:
        tr = ru(f"{subj}\n\n{txt}")
        send((f"📩 {site}: {subj}\n\n{txt}" + (f"\n\n🇷🇺 ПЕРЕВОД:\n{tr}" if tr else ""))[:4000])

    if first:
        send(f"✅ Бот запущен. Слежу за {ok} лентами. Новые посты буду присылать сюда.")
    else:
        for name, title, body, link in found[:15]:
            tr = "" if re.search("[а-яё]", (title + body).lower()) else ru(f"{title}\n\n{body}")
            msg = f"🎸 {name}\n{title}\n\n{body}".replace("\n\n\n", "\n\n")
            if tr:
                msg += f"\n\n🇷🇺 ПЕРЕВОД:\n{tr}"
            send(f"{msg}\n\n{link}"[:4000])

    today = time.strftime("%Y-%m-%d")
    if ok == 0 and st.get("err_day") != today:
        send("⚠️ Reddit не отвечает боту (возможна блокировка). Напиши Claude.")
        st["err_day"] = today

    st["feeds"] = sorted(known)
    st["ids"] = list(seen)[-3000:]
    json.dump(st, open(SEEN_FILE, "w", encoding="utf-8"))
    print(f"Лент: {ok}, ошибок: {fails}, каналов: {tg_ok}, найдено: {len(found)}")

main()
