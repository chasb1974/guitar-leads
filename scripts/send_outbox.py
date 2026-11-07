import os, sys, json, urllib.request, urllib.parse
TOKEN = os.environ["TG_TOKEN"]; CHAT = os.environ["TG_CHAT"]
def send(t):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": t, "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN, data, timeout=30).read()
for path in sys.argv[1:]:
    text = open(path, encoding="utf-8").read().strip()
    while text:
        chunk = text[:3800]
        if len(text) > 3800 and "\n" in chunk:
            chunk = chunk[:chunk.rfind("\n")]
        send(chunk); text = text[len(chunk):].lstrip()
