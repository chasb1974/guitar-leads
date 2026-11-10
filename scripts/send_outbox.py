import os, sys, uuid, urllib.request, urllib.parse, urllib.error

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]
API = "https://api.telegram.org/bot%s/" % TOKEN
LIMIT = 50 * 1024 * 1024  # лимит Bot API на загрузку файла


def send(t):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": t, "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(API + "sendMessage", data, timeout=30).read()


def send_document(path):
    name = os.path.basename(path).replace('"', "_").replace("\r", "_").replace("\n", "_")
    boundary = uuid.uuid4().hex
    head = (
        '--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
        '--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n'
        '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ) % (boundary, CHAT, boundary, name, boundary, name)
    with open(path, "rb") as f:
        content = f.read()
    body = head.encode("utf-8") + content + ("\r\n--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(
        API + "sendDocument",
        body,
        {"Content-Type": "multipart/form-data; boundary=%s" % boundary},
    )
    urllib.request.urlopen(req, timeout=300).read()


failed = False
for path in sys.argv[1:]:
    base = os.path.basename(path)
    if base.lower() == "readme.txt":
        continue
    try:
        if path.lower().endswith(".md"):
            text = open(path, encoding="utf-8").read().strip()
            while text:
                chunk = text[:3800]
                if len(text) > 3800 and "\n" in chunk:
                    chunk = chunk[: chunk.rfind("\n")]
                send(chunk)
                text = text[len(chunk):].lstrip()
        elif os.path.getsize(path) > LIMIT:
            send("Файл %s не отправлен: он больше 50 МБ (лимит Telegram для ботов)." % base)
            failed = True
            print("слишком большой:", base)
            continue
        else:
            send_document(path)
        print("отправлено:", base)
    except urllib.error.HTTPError as e:
        failed = True
        print("ошибка при отправке %s: HTTP %s %s" % (base, e.code, e.read().decode("utf-8", "replace")))
    except Exception as e:
        failed = True
        print("ошибка при отправке %s: %s" % (base, type(e).__name__))

sys.exit(1 if failed else 0)
