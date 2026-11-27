import json
import os
import re
import random
import time

import requests
import telebot
from PIL import Image, ImageDraw, ImageFont

# --- ВСТАВЬ СЮДА НОВЫЙ ТОКЕН ОТ BOTFATHER ---
BOT_TOKEN = "9195858152:AAEwnzFw_jVNiDPYnDj1knl0n1oP-XiXFxU"
# --------------------------------------------

DATA_DIR = "bot_data"
os.makedirs(DATA_DIR, exist_ok=True)

TOXIC_WORDS = ["блять", "сука", "нахуй", "пиздец", "иди нахуй", "заебал", "нахер", "хуйня",
               "ебобошка", "шлюха", "уёбище", "гандон", "проститутки кусок", "говноед",
               "припиздыш", "пидарас", "членонд", "шмара", "спиздешь"]

bot = telebot.TeleBot(BOT_TOKEN)
BOT_ID = bot.get_me().id
BOT_USERNAME = bot.get_me().username

VERSION = "v10: итоговый холст строго квадратный"

# ---------- Шрифт (жирный, с засечками — классика демотиваторов) ----------

FONT_PATH = os.path.join(DATA_DIR, "DemFont-Bold.ttf")

FONT_URLS = [
    "https://github.com/matplotlib/matplotlib/raw/main/lib/matplotlib/mpl-data/fonts/ttf/DejaVuSerif-Bold.ttf",
    "https://github.com/matplotlib/matplotlib/raw/main/lib/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf",
]

def get_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        pass
    for url in FONT_URLS:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            with open(FONT_PATH, "wb") as f:
                f.write(r.content)
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default(size)

# ---------- Память о фото чата (сохраняется на диск) ----------

PHOTOS_DB = {}

def photos_db_path():
    return os.path.join(DATA_DIR, "photos_db.json")

def load_photos_db():
    global PHOTOS_DB
    try:
        with open(photos_db_path(), "r", encoding="utf-8") as f:
            PHOTOS_DB = json.load(f)
    except Exception:
        PHOTOS_DB = {}

def save_photos_db():
    try:
        with open(photos_db_path(), "w", encoding="utf-8") as f:
            json.dump(PHOTOS_DB, f, ensure_ascii=False)
    except Exception:
        pass

def remember_photo(chat_id, file_id):
    lst = PHOTOS_DB.setdefault(str(chat_id), [])
    if file_id in lst:
        lst.remove(file_id)
    lst.insert(0, file_id)
    del lst[25:]
    save_photos_db()

load_photos_db()

# ---------- Модель-«мозг» ----------

class Markov:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.chain = {}
        self.starts = []
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

# ---------- Текст: заголовок + подпись ----------

def split_caption(caption):
    for punct in (". ", "! ", "? "):
        idx = caption.find(punct)
        if idx != -1:
            title = caption[:idx + 1].strip()
            sub = caption[idx + 1:].strip()
            if sub:
                return title, sub
    words = caption.split()
    if len(words) < 4:
        return caption, ""
    mid = (len(words) + 1) // 2
    return " ".join(words[:mid]), " ".join(words[mid:])

# ---------- Перенос и подбор размера ----------

def wrap_lines(text, font, max_w):
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if font.getlength(test) > max_w and line:
            lines.append(line)
            line = w
        else:
            line = test
    if line:
        lines.append(line)
    return lines

def fit_text(text, max_w, max_h, start, min_size=14):
    for size in range(start, min_size - 1, -2):
        font = get_font(size)
        lines = wrap_lines(text, font, max_w)
        line_h = int(size * 1.25)
        widest = max(font.getlength(ln) for ln in lines)
        if len(lines) * line_h <= max_h and widest <= max_w:
            return font, lines, line_h, size
    font = get_font(min_size)
    lines = wrap_lines(text, font, max_w)
    return font, lines, int(min_size * 1.25), min_size

# ---------- Метка версии в углу демотиватора ----------

def stamp_version(d, canvas):
    tag = VERSION.split(":")[0]
    font = get_font(14)
    w = int(font.getlength(tag))
    d.text((canvas.width - w - 10, canvas.height - 24), tag,
           fill=(120, 120, 120), font=font)

# ---------- Демотиваторы ----------

def draw_two_tier(d, center_x, max_w, zone_top, zone_h, title, subtitle, fill):
    if subtitle:
        title_zone = int(zone_h * 0.55)
        sub_zone = zone_h - title_zone - 14
    else:
        title_zone = zone_h
        sub_zone = 0

    font_t, lines_t, lh_t, size_t = fit_text(title, max_w, title_zone, start=52)
    lines_s, font_s, lh_s = [], None, 0
    if subtitle:
        sub_start = max(14, int(size_t * 0.55))
        font_s, lines_s, lh_s, _ = fit_text(subtitle, max_w, sub_zone, start=sub_start)

    block_h = len(lines_t) * lh_t
    if subtitle:
        block_h += 14 + len(lines_s) * lh_s

    top = zone_top + (zone_h - block_h) // 2

    y = top
    for ln in lines_t:
        d.text((center_x, y + lh_t / 2), ln, fill=fill, font=font_t, anchor="mm")
        y += lh_t
    if subtitle:
        y += 14
        for ln in lines_s:
            d.text((center_x, y + lh_s / 2), ln, fill=fill, font=font_s, anchor="mm")
            y += lh_s


def make_demotivator(src, caption):
    img = Image.open(src).convert("RGB")

    # --- ВСЁ СЧИТАЕТСЯ ОТ КВАДРАТНОГО ХОЛСТА ---
    CANVAS = 800   # итоговый размер картинки: 800 x 800, всегда квадрат
    MARGIN = 30    # черные поля вокруг рамки
    BORDER = 3     # толщина белой рамки
    TEXT_H = 170   # высота черной зоны под текст

    # фото = холст минус поля, рамка и текстовая зона — тоже квадрат
    PHOTO = CANVAS - MARGIN * 2 - BORDER * 2 - TEXT_H  # 564

    photo = img.resize((PHOTO, PHOTO))

    framed = Image.new("RGB", (photo.width + BORDER * 2,
                               photo.height + BORDER * 2), (255, 255, 255))
    framed.paste(photo, (BORDER, BORDER))

    W = CANVAS
    H = CANVAS  # ширина = высота, ровный квадрат со всех сторон
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(framed, (MARGIN, MARGIN))

    title, subtitle = split_caption(caption.strip())

    d = ImageDraw.Draw(canvas)
    zone_top = framed.height + MARGIN * 2
    draw_two_tier(d, W / 2, W - MARGIN * 2, zone_top, TEXT_H,
                  title, subtitle, fill=(255, 255, 255))
    stamp_version(d, canvas)

    out = os.path.join(DATA_DIR, f"dem_{int(time.time() * 1000)}.jpg")
    canvas.save(out, quality=95)
    return out


def make_text_demotivator(caption):
    W, H = 800, 800
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)

    title, subtitle = split_caption(caption.strip())
    draw_two_tier(d, W / 2, W - 100, 40, H - 80, title, subtitle, fill=(255, 255, 255))
    stamp_version(d, img)

    out = os.path.join(DATA_DIR, f"demtxt_{int(time.time() * 1000)}.jpg")
    img.save(out, quality=95)
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

# ---------- Команда «д д д» ----------

@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() == "д д д" and m.reply_to_message)
def ddd_with_photo(m):
    target = m.reply_to_message
    if not target.photo:
        bot.send_message(m.chat.id, "Реплай должен быть на фото!")
        return
    try:
        photo_to_dem(m.chat.id, target, None)
    except Exception as e:
        bot.send_message(m.chat.id, f"Не вышло: {e}")

@bot.message_handler(func=lambda m: m.text and m.text.lower().strip().startswith("д д д"))
def ddd_from_text(m):
    caption = m.text[5:].strip()

    if not caption:
        s = load_settings(m.chat.id)
        caption = get_model(m.chat.id).gen(toxic=s.get("toxic", False)) or "..."
        if not caption or caption == "...":
            caption = random.choice([
                "всё тлен", "я не просил такой жизни",
                "устал, ложусь", "ничего не понимаю, но смешно"
            ])

    pool = PHOTOS_DB.get(str(m.chat.id))
    out = None
    if pool:
        file_id = random.choice(pool)
        try:
            file_info = bot.get_file(file_id)
            data = bot.download_file(file_info.file_path)
            src = os.path.join(DATA_DIR, f"src_{int(time.time() * 1000)}.jpg")
            with open(src, "wb") as f:
                f.write(data)
            out = make_demotivator(src, caption)
        except Exception as e:
            bot.send_message(m.chat.id, f"Не вышло: {e}")
            return
    if out is None:
        out = make_text_demotivator(caption)

    with open(out, "rb") as f:
        bot.send_photo(m.chat.id, f)

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
        "«д д д» реплаем на фото — демотиватор\n"
        "«д д д фраза» — картинка из чата с вашей фразой\n"
        "/stats — сколько я выучил\n"
        "/version — какая версия у меня на борту\n"
        "/forget — забыть всё выученное (только админ)")

@bot.message_handler(commands=["start", "help"])
def cmd_help(m):
    bot.send_message(m.chat.id, HELP)

@bot.message_handler(commands=["version"])
def cmd_version(m):
    bot.send_message(m.chat.id, "Версия: " + VERSION)

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

    model = get_model(m.chat.id)
    model.learn(m.text)
    if len(model.starts) % 30 == 0:
        model.save()

    text_lower = m.text.lower()
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
    remember_photo(m.chat.id, m.photo[-1].file_id)
    s = load_settings(m.chat.id)
    if random.randint(1, 100) <= s.get("dem_prob", 20):
        photo_to_dem(m.chat.id, m, None)

print("=== ЗАПУЩЕНА ВЕРСИЯ:", VERSION, "===")
bot.infinity_polling(skip_pending=True)
