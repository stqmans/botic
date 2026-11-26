import json
import os
import re
import random
import time

import telebot
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = "9195858152:AAEwnzFw_jVNiDPYnDj1knl0n1oP-XiXFxU"

DATA_DIR = "bot_data"
os.makedirs(DATA_DIR, exist_ok=True)

TOXIC_WORDS = ["блять", "сука", "нахуй", "пиздец", "иди нахуй", "заебал", "нахер", "хуйня",
               "ебобошка", "шлюха", "уёбище", "гандон", "проститутки кусок", "говноед",
               "припиздыш", "пидарас", "членонд", "шмара", "спиздешь"]

bot = telebot.TeleBot(BOT_TOKEN)
BOT_ID = bot.get_me().id
BOT_USERNAME = bot.get_me().username

# ---------- Модель-«мозг» ----------

class Markov:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.chain = {}    # слово -> {следующее слово: сколько раз}
        self.starts = []   # слова, с которых начинаются фразы
        self.load()

    def _path(self):
        return os.path.join(DATA_DIR, f"markov_{self.chat_id}.json")

    def load(self):
        try:
            with open(self._path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self.chain = data.get("chain", {})
            self.starts = data.get("starts", [])
        except FileNotFoundError:
            self.chain = {}
            self.starts = []

    def save(self):
        with open(self._path(), "w", encoding="utf-8") as f:
            json.dump({"chain": self.chain, "starts": self.starts}, f, ensure_ascii=False)

    def learn(self, text):
        words = re.findall(r"[а-яёa-z0-9]+", text.lower())
        if len(words) < 2:
            return
        self.starts.append(words[0])
        for i, w in enumerate(words[:-1]):
            nxt = words[i + 1]
            self.chain.setdefault(w, {})
            self.chain[w][nxt] = self.chain[w].get(nxt, 0) + 1
        self.save()

    def wipe(self):
        self.chain = {}
        self.starts = []
        self.save()

    def stats(self):
        return len(self.chain), len(self.starts)

    def gen(self, seed=None, toxic=False, max_words=20):
        if not self.chain or not self.starts:
            return None
        word = seed if (seed and seed in self.chain) else random.choice(self.starts)
        result = [word]
        for _ in range(max_words - 1):
            nxts = self.chain.get(word)
            if not nxts:
                break
            if not toxic:
                nxts = {w: c for w, c in nxts.items() if w not in TOXIC_WORDS}
                if not nxts:
                    break
            variants, weights = zip(*nxts.items())
            word = random.choices(variants, weights=weights)[0]
            result.append(word)
        return " ".join(result)

MODELS = {}

def get_model(chat_id):
    if chat_id not in MODELS:
        MODELS[chat_id] = Markov(chat_id)
    return MODELS[chat_id]

# ---------- Настройки чата ----------

def settings_path(chat_id):
    return os.path.join(DATA_DIR, f"settings_{chat_id}.json")

def load_settings(chat_id):
    try:
        with open(settings_path(chat_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"prob": 5, "toxic": False, "dem_prob": 20}

def save_settings(chat_id, s):
    with open(settings_path(chat_id), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)

def is_admin(m):
    try:
        member = bot.get_chat_member(m.chat.id, m.from_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

# ---------- Демотиватор ----------

def make_demotivator(src, caption):
    img = Image.open(src).convert("RGB")
    img.thumbnail((900, 700))
    margin = 60
    canvas = Image.new("RGB", (img.width + margin * 2, img.height + margin * 2 + 100), (0, 0, 0))
    canvas.paste(img, (margin, margin))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    lines = []
    line = ""
    for word in caption.split():
        if len(line) + len(word) + 1 > 40:

            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    y = margin + img.height + 10
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        x = (canvas.width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), ln, fill="white", font=font)
        y += (bbox[3] - bbox[1]) + 10
    out = os.path.join(DATA_DIR, f"dem_{int(time.time() * 1000)}.jpg")
    canvas.save(out)
    return out

def photo_to_dem(chat_id, msg, caption):
    if not caption:
        s = load_settings(chat_id)
        caption = get_model(chat_id).gen(toxic=s.get("toxic", False)) or "..."
    file_info = bot.get_file(msg.photo[-1].file_id)
    data = bot.download_file(file_info.file_path)
    src = os.path.join(DATA_DIR, f"src_{int(time.time() * 1000)}.jpg")
    with open(src, "wb") as f:
        f.write(data)
    out = make_demotivator(src, caption)
    with open(out, "rb") as f:
        bot.send_photo(chat_id, f, reply_to_message_id=msg.message_id)

# ---------- «Свои» реплики ----------

# ---------- «Свои» реплики ----------

def own_remark(model):
    if random.random() < 0.6 and model.chain:
        w = random.choice(list(model.chain.keys()))
        templates = [
            "меня всю жизнь интересует {w}, но я молчал до этой минуты",
            "если подумать, {w} — самое честное слово в этом чате",
            "{w}? ну да. конечно. как всегда",
            "предлагаю официально признать {w} смыслом жизни",
            "у меня нет личности, зато есть {w}",
            "кто-нибудь ещё заметил {w} или только я?",
            "я бы на месте {w} уже уволился",
        ]
        return random.choice(templates).format(w=w)
    return None


def maybe_reply(m, force=False, seed_text=None):
    s = load_settings(m.chat.id)
    if not force and random.randint(1, 100) > s["prob"]:
        return
    model = get_model(m.chat.id)
    if random.randint(1, 100) <= s.get("own_prob", 10):
        text = own_remark(model)
        if text:
            bot.send_message(m.chat.id, text, reply_to_message_id=m.message_id)
            return
    seed = None
    if seed_text:
        for w in re.findall(r"[а-яёa-z0-9]+", seed_text.lower()):
            if w in model.chain:
                seed = w
                break
    text = model.gen(seed=seed, toxic=s.get("toxic", False))
    if text:
        bot.send_message(m.chat.id, text, reply_to_message_id=m.message_id)

# ---------- Команды ----------

HELP = ("Я учусь на ваших сообщениях и огрызаюсь.\n\n"
        "Команды:\n"
        "/prob N — шанс моего ответа в % (1–100, для админов)\n"
        "/demprob N — шанс демотиватора с обычного фото (0–100, для админов)\n"
        "/toxic on|off — включить/выключить мат\n"
        "/say — заставить меня ответить (или /say слово)\n"
        "/dem подпись — реплаем на фото: сделаю демотиватор\n"
        "/stats — сколько я выучил\n"
        "/forget — забыть всё выученное (только админ)")

@bot.message_handler(commands=["start", "help"])
def cmd_help(m):
    bot.send_message(m.chat.id, HELP)

@bot.message_handler(commands=["prob"])
def cmd_prob(m):
    if not is_admin(m):
        bot.send_message(m.chat.id, "Только админы меня настраивают.")
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(m.chat.id, "Формат: /prob 15")
        return
    val = max(1, min(100, int(parts[1])))
    s = load_settings(m.chat.id); s["prob"] = val; save_settings(m.chat.id, s)
    bot.send_message(m.chat.id, f"Ок, теперь отвечаю с шансом {val}%.")

@bot.message_handler(commands=["demprob"])
def cmd_demprob(m):
    if not is_admin(m):
        bot.send_message(m.chat.id, "Только админы меня настраивают.")
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(m.chat.id, "Формат: /demprob 50")
        return
    val = max(0, min(100, int(parts[1])))
    s = load_settings(m.chat.id); s["dem_prob"] = val; save_settings(m.chat.id, s)
    bot.send_message(m.chat.id, f"Теперь делаю демотиваторы с шансом {val}%.")

@bot.message_handler(commands=["toxic"])
def cmd_toxic(m):
    if not is_admin(m):
        bot.send_message(m.chat.id, "Только админы меня настраивают.")
        return
    arg = (m.text or "").split()[-1].lower()
    if arg not in ("on", "off"):
        bot.send_message(m.chat.id, "Формат: /toxic on или /toxic off")
        return
    s = load_settings(m.chat.id); s["toxic"] = arg == "on"; save_settings(m.chat.id, s)
    bot.send_message(m.chat.id, "Мат-режим: " + ("ВКЛ 🔥" if arg == "on" else "выкл"))

@bot.message_handler(commands=["say"])
def cmd_say(m):
    seed = m.text.split(maxsplit=1)[1] if " " in m.text else None
    maybe_reply(m, force=True, seed_text=seed)

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    ch, st = get_model(m.chat.id).stats()
    bot.send_message(m.chat.id, f"Выучено слов: {ch}, начальных фраз: {st}.")

@bot.message_handler(commands=["forget"])
def cmd_forget(m):
    if not is_admin(m):
        bot.send_message(m.chat.id, "Только админы меня настраивают.")
        return
    get_model(m.chat.id).wipe()
    bot.send_message(m.chat.id, "Всё забыл. Можно начинать заново.")

@bot.message_handler(commands=["dem"])
def cmd_dem(m):
    target = m.reply_to_message
    if not target or not target.photo:
        bot.send_message(m.chat.id, "Отправь эту команду реплаем на фото: /dem и подпись")
        return
    caption = m.text.split(maxsplit=1)[1] if " " in (m.text or "") else None
    try:
        photo_to_dem(m.chat.id, target, caption)
    except Exception as e:
        bot.send_message(m.chat.id, f"Не вышло: {e}")

@bot.message_handler(content_types=["photo"],
                     func=lambda m: (m.caption or "").lower().startswith("/dem"))
def cmd_dem_caption(m):
    caption = m.caption.split(maxsplit=1)[1] if " " in m.caption else None
    try:
        photo_to_dem(m.chat.id, m, caption)
    except Exception as e:
        bot.send_message(m.chat.id, f"Не вышло: {e}")

# ---------- Основная логика ----------

@bot.message_handler(content_types=["text"],
                     func=lambda m: m.chat.type in ("group", "supergroup"))
def on_text(m):
    if not m.text or m.text.startswith("/"):
        return

    text_lower = m.text.lower()
    if text_lower.startswith("d d d"):
        caption = m.text.split("d d d", 1)[1].strip() or None
        target = m.reply_to_message
        if target and target.photo:
            try:
                photo_to_dem(m.chat.id, target, caption)
            except Exception as e:
                bot.send_message(m.chat.id, f"Не вышло: {e}")
        else:
            bot.send_message(m.chat.id, "Отправь это реплаем на фото: d d d и подпись")
        return

    model = get_model(m.chat.id)
    model.learn(m.text)
    if len(model.starts) % 30 == 0:
        model.save()

    mentioned = BOT_USERNAME and (f"@{BOT_USERNAME}" in text_lower)
    replied_to_bot = m.reply_to_message and m.reply_to_message.from_user.id == BOT_ID
    if mentioned or replied_to_bot:
        maybe_reply(m, force=True, seed_text=m.text)
    else:
        maybe_reply(m)

@bot.message_handler(content_types=["photo"],
                     func=lambda m: m.chat.type in ("group", "supergroup")
                     and not (m.caption or "").startswith("/dem"))
def on_photo(m):
    s = load_settings(m.chat.id)
    if random.randint(1, 100) <= s.get("dem_prob", 20):
        photo_to_dem(m.chat.id, m, None)

print("Бот запущен")
bot.infinity_polling(skip_pending=True)