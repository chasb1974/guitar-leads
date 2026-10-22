# Бот поиска заказов: следит за Reddit и шлёт подходящие посты в Telegram.
import html as html_mod, os, json, re, time, imaplib, email, urllib.request, urllib.parse, urllib.error, xml.etree.ElementTree as ET
from email.header import decode_header, make_header

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]

# ---- ГДЕ ИСКАТЬ (можно дописывать свои строки) ----
SUBS = ["SunoAI", "udiomusic", "WeAreTheMusicMakers", "musicians",
        "songwriters", "makingmusic", "HireAMusician", "forhire"]
SEARCH = ["need guitarist", "session guitarist", "real guitar suno",
          "live guitar ai song", "hire guitar player"]

# ---- ЧТО ИСКАТЬ ----
# Нужны люди, которые хотят ЗАПИСАТЬ гитару в свой трек (не уроки, не "в группу", не концерт).
GUITAR = ["guitar", "гитар"]
# Ищут именно гитариста / гитарную партию
SEEK_RE = re.compile(r"guitarists?\b|guitar players?\b|someone to play guitar|play (?:the |some )?guitars? on|"
                     r"guitar parts?\b|guitar tracks?\b|real guitars?\b|live guitars?\b|human guitar|"
                     r"гитарист|живую гитару|живая гитара|партию гитары|гитарную партию")
# Признаки записи в трек (а не выступления)
REC_RE = re.compile(r"\brecord(?:ing|ed)?\b|re-?record|\btracks?\b|my song|my demo|my album|\bep\b|"
                    r"\bsuno\b|\budio\b|\bai[- ](?:song|track|music|generated)|\bstems?\b|\bremote(?:ly)?\b|"
                    r"\bonline\b|\bsolo on\b|\breplace\b|"
                    r"запис|трек|удал[её]нн|онлайн")
# Кто-то ИЩЕТ (а не предлагает и не рассказывает)
ASK_RE = re.compile(r"\blooking for\b|\bneed\b|\bneeded\b|\bwanted\b|\bhire\b|\bhiring\b|"
                    r"\banyone (?:who|here|that|able|willing|can|could|want)|"
                    r"\bwho can\b|\bcan someone\b|\bwould someone\b|\bsearching for\b|"
                    r"ищу|ищем|нужен|нужна|требуется|кто может|кто сможет")
# Признаки живых выступлений / набора в группу
LIVE_RE = re.compile(r"\bband\b|bandmates|band members|\bgigs?\b|private event|tonight|"
                     r"live opportunit|cover band|wedding|audition|в группу|кавер|концерт|выступлен")
# Признаки оплаты (целые слова, чтобы "rate" не ловилось в "generated")
MONEY_RE = re.compile(r"\$\s?\d|\d\s?\$|\bpaid\b|\bpay\b|\bpaying\b|\bbudget\b|\busd\b|€|£|"
                      r"\bfee\b|\brates?\b|\bcompensat|\bhire\b|\bhiring\b|"
                      r"оплат|заплач|бюджет|гонорар|за деньги|платн|₽|\bруб|тенге|\bтг\b")
# Мусор в ЗАГОЛОВКЕ: сами предлагают услуги, просят отзыв, показывают своё, реклама
SKIP_TITLE = ["for hire", "[offer]", "feedback", "review", "rate my", "check out",
              "my new song", "my new track", "tutorial", "how do i", "how to ",
              "plugin", "preset", "free download", "giveaway", "kontakt", "sale",
              "looking for gigs", "who needs a", "what amp", "pedal", " vs ", "tone"]
# Мусор в ЛЮБОМ месте: уроки, без денег, предложение своих услуг
SKIP = ["available for", "my services", "i offer", "i'm offering", "i am offering",
        "i am a session", "i'm a session", "guitar lessons", "guitar teacher", "teach guitar",
        "[for hire]", "my name is", "i'm a producer", "i am a producer", "i'm an independent",
        "hmu if you need", "if you need a guitarist", "i'm a guitarist", "i am a guitarist",
        "years of experience", "my portfolio",
        "unpaid", "no budget", "for exposure", "rev share", "revenue share",
        "ищу группу", "ищу коллектив", "преподавател", "педагог",
        "уроки", "бесплатно", "без оплаты"]
# Для старой проверки Telegram-каналов
HIRE = []

def why_not(title, body):
    """Пусто, если пост подходит; иначе причина, почему отброшен."""
    tl = title.lower()
    t = (title + " " + body).lower()
    if not any(g in t for g in GUITAR):
        return "нет гитары"
    for x in SKIP_TITLE:
        if x in tl:
            return "заголовок: " + x
    for x in SKIP:
        if x in t:
            return "мусор: " + x
    seek = bool(SEEK_RE.search(t))
    rec = bool(REC_RE.search(t))
    if ("[hiring]" in tl or "[paid]" in tl) and seek:
        return ""
    if not ASK_RE.search(t):
        return "никто не ищет"
    if not seek:
        return "ищут не гитариста"
    if LIVE_RE.search(tl):
        return "группа / концерт"
    if LIVE_RE.search(t) and not rec:
        return "группа / концерт"
    if rec or MONEY_RE.search(t):
        return ""
    return "не про запись"

def match(text, body=""):
    return why_not(text, body) == ""

# ---- TELEGRAM-КАНАЛЫ (публичные, читаем веб-версию t.me/s/...) ----
TG_CHANNELS = ["musiclance", "musician_msk", "spbmuzpoisk", "bandlinksoundcheck"]
# В каналах нужна именно запись/сессия, а не "ищем гитариста в группу"
TG_WORK = ["запис", "сессион", "студи", "трек", "партию", "партии", "удалён", "удален",
           "онлайн", "дистанц", "аранжиров", "session", "record", "remote"]

SEEN_FILE = "seen.json"
REPORT_FILE = "report.json"
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

# Посты-анкеты «ищу группу» / «группа ищет музыканта» — это набор в коллектив, не запись
TG_BAND_RE = re.compile(r"ищет группу|ищу группу|ищу коллектив|ищет коллектив|группа ищет|"
                        r"коллектив ищет|ищем в (?:группу|состав|коллектив)|в состав|"
                        r"название группы|кавер|концерт|выступлен|репетиц|репбаз|"
                        r"корпоратив|свадьб|кабак|ресторан|по выходным")
# Нужна именно запись партии (одно из этих слов обязательно)
TG_REC_RE = re.compile(r"запис|сессион|удал[её]нн|дистанц|онлайн|в трек|для трека|"
                       r"на трек|в песню|для песни|session|record|remote")
# Кого ищут: строка «Кого ищете: ...» должна упоминать гитару
TG_WHO_RE = re.compile(r"кого ищ[её]те\s*:?\s*([^0-9\n]{0,80})")

def tg_why_not(text):
    """Пусто, если пост из канала подходит; иначе причина."""
    t = text.lower()
    if not any(g in t for g in GUITAR):
        return "нет гитары"
    for x in SKIP:
        if x in t:
            return "мусор: " + x
    if TG_BAND_RE.search(t):
        return "группа / концерт"
    who = TG_WHO_RE.search(t)
    if who and "гитар" not in who.group(1):
        return "ищут не гитариста"
    if not SEEK_RE.search(t):
        return "ищут не гитариста"
    if not TG_REC_RE.search(t):
        return "не про запись"
    return ""

def tg_match(text):
    return tg_why_not(text) == ""

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

# ---- AIRGIGS: доска проектов «Artists Wanted» (открыта без входа) ----
AG_BASE = "https://www.airgigs.com"
AG_PAGES = 3          # сколько страниц доски смотреть (по 28 проектов, свежие сверху)
AG_GUITAR_RE = re.compile(r"guitar|гитар|fingerstyle|ukulele|укулеле")
# Не наше: уроки, расшифровка нот, набор в группу, работа без оплаты
AG_SKIP_TITLE_RE = re.compile(r"transcri|sheet music|\btabs?\b|tablature|lead sheet|\blessons?\b")
AG_SKIP_RE = re.compile(r"\blessons?\b|\bteach|\btutor|"
                        r"join (?:my|our|a) band|band member|cover band|wedding|audition|"
                        r"\bunpaid\b|no budget|for exposure|rev(?:enue)?[- ]share|royalt(?:y|ies) only|"
                        r"\bfree\b.{0,20}\b(?:collab|project)")

def ag_allowed():
    """Уважаем robots.txt: если сайт запретил роботам доску, не читаем."""
    try:
        import urllib.robotparser
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(get(AG_BASE + "/robots.txt").decode("utf-8", "replace").splitlines())
        return rp.can_fetch("*", AG_BASE + "/job_board?page=1")
    except Exception as e:
        print("AirGigs robots.txt не прочитан, продолжаю:", e)
        return True

def ag_list(page):
    """Список проектов страницы: [(id, заголовок)]."""
    html = get(f"{AG_BASE}/job_board?page={page}").decode("utf-8", "replace")
    return [(i, clean(t)) for i, t in re.findall(
        r'<h4 class="post-title job-title"><a href="https://www\.airgigs\.com/job/(\d+)">(.*?)</a></h4>', html, re.S)]

def ag_job(jid):
    """Полный проект: (заголовок, жанры, описание)."""
    html = get(f"{AG_BASE}/job/{jid}").decode("utf-8", "replace")
    m = re.search(r'<h2 style="word-wrap: break-word;">(.*?)</h2>', html, re.S)
    title = clean(m.group(1)) if m else ""
    m = re.search(r'<p class="item_label">(.*?)</p>', html, re.S)
    genres = ", ".join(clean(x) for x in re.findall(r"<small[^>]*>(.*?)</small>", m.group(1), re.S)) if m else ""
    m = re.search(r'id="description"[^>]*>(.*?)id="audio_play"', html, re.S)
    body = m.group(1).replace("<br>", " ").replace("<br/>", " ") if m else ""
    body = re.sub(r"</div>\s*<div class=\"tab-block\".*$", " ", body, flags=re.S)
    body = html_mod.unescape(clean(body))
    body = re.sub(r"https?://\S+", "", body)                       # ссылки на YouTube и диски не нужны в тексте
    body = re.sub(r"Read (?:More|Less)|prop-read-(?:more|less)|<div class=\"tab-block\"", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    if title and body.startswith(title):
        body = body[len(title):].strip()
    return title, genres, body

def ag_why_not(title, body):
    t = (title + " " + body).lower()
    if not AG_GUITAR_RE.search(t):
        return "нет гитары"
    m = AG_SKIP_TITLE_RE.search(title.lower()) or AG_SKIP_RE.search(t)
    if m:
        return "мусор: " + m.group(0)
    return ""

def ag_check(seen, quiet):
    """Новые проекты AirGigs про гитару: [(заголовок, жанры, текст, ссылка)]."""
    out = []
    if not ag_allowed():
        print("AirGigs: robots.txt запрещает, пропускаю")
        return out, False
    items = []
    for p in range(1, AG_PAGES + 1):
        items += ag_list(p)
        time.sleep(2)
    fresh = [(i, t) for i, t in items if "ag:" + i not in seen]
    for i, t in fresh:
        seen.add("ag:" + i)
    if quiet:
        return out, True
    for i, t in fresh[:40]:
        try:
            title, genres, body = ag_job(i)
        except Exception as e:
            print("AirGigs проект", i, e)
            continue
        time.sleep(2)
        why = ag_why_not(title or t, body)
        print("AirGigs", i, (title or t)[:50], "->", why or "ОК")
        if not why:
            out.append((title or t, genres, body[:700], f"{AG_BASE}/job/{i}"))
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
    report = []

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
            if not pid:
                continue
            title = en.findtext(A + "title") or ""
            body = clean(en.findtext(A + "content"))
            link = en.find(A + "link").get("href")
            reason = why_not(title, body)
            if reason != "нет гитары":
                report.append({"id": pid, "src": name, "title": title[:200],
                               "text": body[:400], "link": link,
                               "ok": reason == "", "why": reason})
            if pid in seen:
                continue
            seen.add(pid)
            if not quiet and reason == "":
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

    try:
        aquiet = "airgigs" not in known
        ag_jobs, ag_on = ag_check(seen, aquiet)
        if ag_on:
            known.add("airgigs")
            if aquiet:
                send("🎯 Подключил доску проектов AirGigs. Буду присылать новые заказы про гитару.")
        for title, genres, body, link in ag_jobs[:10]:
            tr = ru(f"{title}\n\n{body}")
            msg = f"🎯 AirGigs: {title}" + (f"\nЖанры: {genres}" if genres else "") + f"\n\n{body}"
            if tr:
                msg += f"\n\n🇷🇺 ПЕРЕВОД:\n{tr}"
            send(f"{msg}\n\n{link}"[:4000])
    except Exception as e:
        print("Ошибка AirGigs", e)
        if st.get("ag_err_day") != time.strftime("%Y-%m-%d"):
            send("⚠️ Не получается прочитать доску AirGigs. Напиши Claude.")
            st["ag_err_day"] = time.strftime("%Y-%m-%d")

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

    # Отчёт для Claude: все посты про гитару из последних лент и решение бота
    try:
        old = json.load(open(REPORT_FILE, encoding="utf-8"))
    except Exception:
        old = []
    ids = {r["id"] for r in report}
    report = (report + [r for r in old if r["id"] not in ids])[:300]
    json.dump(report, open(REPORT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    st["feeds"] = sorted(known)
    st["ids"] = list(seen)[-3000:]
    json.dump(st, open(SEEN_FILE, "w", encoding="utf-8"))
    print(f"Лент: {ok}, ошибок: {fails}, каналов: {tg_ok}, найдено: {len(found)}")

main()
