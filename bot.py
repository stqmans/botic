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

VERSION = "v14: классика как на образце + случайное фото если пул пуст"

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
        with open(settings_path(chat_id), "r", encoding="utf-8")
