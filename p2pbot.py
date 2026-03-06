import matplotlib.pyplot as plt
from datetime import datetime
import requests
import sqlite3
import csv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

BOT_TOKEN = "8503792556:AAE14E9hzN3ppo9ONcXVc2_cfNLZ9tsFe-Q"

YOUR_CHAT_ID = 822462684
FRIEND_CHAT_ID = 6042777779

# ================= DATABASE =================

conn = sqlite3.connect("exchange.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS trades (
id INTEGER PRIMARY KEY AUTOINCREMENT,
chat_id INTEGER,
side TEXT,
base TEXT,
quote TEXT,
base_amount REAL,
quote_amount REAL,
price REAL,
created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS deposit (
id INTEGER PRIMARY KEY AUTOINCREMENT,
chat_id INTEGER,
amount REAL,
type TEXT,
created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS circles (
id INTEGER PRIMARY KEY AUTOINCREMENT,
chat_id INTEGER,
created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS circle_trades (
id INTEGER PRIMARY KEY AUTOINCREMENT,
circle_id INTEGER,
side TEXT,
usdt REAL,
fiat REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
chat_id INTEGER PRIMARY KEY
)
""")

conn.commit()

WAITING = {}
CURRENT_CIRCLE = {}

# ================= UI =================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📊 Цена"],
            ["⭕ Создать круг","📚 Круги"],
            ["💳 Взять депозит","💵 Вернуть депозит","💼 Депозит"]
        ],
        resize_keyboard=True
    )

def circle_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🟢 Купил","🔴 Продал"],
            ["💾 Сохранить круг"]
        ],
        resize_keyboard=True
    )

# ================= BINANCE =================

def get_usdt_kzt_full():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "asset": "USDT",
        "fiat": "KZT",
        "tradeType": "BUY",
        "page": 1,
        "rows": 5
    }
    r = requests.post(url, json=payload, timeout=10)
    items = r.json().get("data", [])

    offers = []
    for item in items:
        price = float(item["adv"]["price"])
        nick = item["advertiser"]["nickName"]
        if item["adv"].get("tradeMethods"):
            bank = item["adv"]["tradeMethods"][0].get("bankName", "—")
        else:
            bank = "—"

        min_amount = float(item["adv"]["minSingleTransAmount"])
        max_amount = float(item["adv"]["maxSingleTransAmount"])
        offers.append((price, nick, bank, min_amount, max_amount))

    offers.sort(key=lambda x: x[0])
    return offers if len(offers) > 0 else []

def get_usdt_try_full(trade_type="BUY"):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "asset": "USDT",
        "fiat": "TRY",
        "tradeType": trade_type,
        "page": 1,
        "rows": 5
    }
    r = requests.post(url, json=payload, timeout=10)
    items = r.json().get("data", [])

    offers = []
    for item in items:
        price = float(item["adv"]["price"])
        nick = item["advertiser"]["nickName"]
        if item["adv"].get("tradeMethods"):
            bank = item["adv"]["tradeMethods"][0].get("bankName", "—")
        else:
            bank = "—"

        min_amount = float(item["adv"]["minSingleTransAmount"])
        max_amount = float(item["adv"]["maxSingleTransAmount"])
        offers.append((price, nick, bank, min_amount, max_amount))

    if trade_type.upper() == "SELL":
        offers.sort(key=lambda x: x[0], reverse=True)
    else:
        offers.sort(key=lambda x: x[0])

    return offers if len(offers) > 0 else []

# ================= CIRCLES =================

def circle_stats(circle_id):
    rows = cursor.execute(
        "SELECT side,usdt,fiat FROM circle_trades WHERE circle_id=?",
        (circle_id,)
    ).fetchall()

    buy_usdt = 0
    sell_usdt = 0
    spent = 0
    received = 0

    for side, usdt, fiat in rows:
        if side == "BUY":
            buy_usdt += usdt
            spent += fiat
        else:
            sell_usdt += usdt
            received += fiat

    profit = received - spent

    percent = 0
    if spent > 0:
        percent = (profit / spent) * 100

    return buy_usdt, sell_usdt, profit, percent

# ================= CHART =================

def circle_chart():
    rows = cursor.execute("""
    SELECT circles.id
    FROM circles
    ORDER BY id
    """).fetchall()

    if not rows:
        return None

    profits = []
    ids = []

    for r in rows:
        circle_id = r[0]
        stats = circle_stats(circle_id)
        profits.append(stats[2])
        ids.append(circle_id)

    plt.figure(figsize=(8,4))
    plt.plot(ids, profits, marker="o")
    plt.axhline(0)
    plt.title("Profit by Circles")
    plt.xlabel("Circle")
    plt.ylabel("Profit")
    plt.grid()
    path = "circle_profit.png"
    plt.savefig(path)
    plt.close()
    return path

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR IGNORE INTO settings (chat_id) VALUES (?)", (chat_id,))
    conn.commit()

    await update.message.reply_text(
        "🤖 IT_Exchange запущен",
        reply_markup=main_keyboard()
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    chat_ids = (YOUR_CHAT_ID, FRIEND_CHAT_ID)

    if chat_id in WAITING:
        step = WAITING[chat_id]

        # обработка запроса цены
        if "price_query" in step:
            txt = text.strip().lower()
            if "покуп" in txt:
                offers = get_usdt_kzt_full()
                msg = "📊 Лучшие предложения USDT/KZT (покупка):\n\n"
                for price, nick, bank, min_amt, max_amt in offers:
                    msg += f"💰 {price:.2f} KZT | 🏦 {bank} | 👤 {nick} | Сумма: {min_amt}-{max_amt} KZT\n"
                await update.message.reply_text(msg, reply_markup=main_keyboard())
                del WAITING[chat_id]
                return
            elif "продаж" in txt or "продажа" in txt or "продать" in txt:
                offers = get_usdt_try_full("SELL")
                msg = "📊 Лучшие предложения USDT/TRY (продажа):\n\n"
                for price, nick, bank, min_amt, max_amt in offers:
                    msg += f"💰 {price:.2f} TRY | 🏦 {bank} | 👤 {nick} | Сумма: {min_amt}-{max_amt} TRY\n"
                await update.message.reply_text(msg, reply_markup=main_keyboard())
                del WAITING[chat_id]
                return
            else:
                await update.message.reply_text("Ответьте 'Покупка' или 'Продажа'")
                return

        # обработка депозита
        if "deposit_action" in step:
            try:
                amount = float(text)
            except:
                await update.message.reply_text("Введите число")
                return

            action = step["deposit_action"]
            cursor.execute(
                "INSERT INTO deposit (chat_id, amount, type, created_at) VALUES (?, ?, ?, datetime('now'))",
                (chat_id, amount, action)
            )
            conn.commit()

            total_withdraw = cursor.execute("SELECT SUM(amount) FROM deposit WHERE type='withdraw'").fetchone()[0] or 0
            total_return = cursor.execute("SELECT SUM(amount) FROM deposit WHERE type='return'").fetchone()[0] or 0
            balance = total_withdraw - total_return

            await update.message.reply_text(
                f"✅ Операция записана: {action} {amount:.2f} KZT\n"
                f"💰 Всего взято: {total_withdraw:.2f}\n"
                f"💵 Всего возвращено: {total_return:.2f}\n"
                f"⚖ Баланс: {balance:.2f} KZT",
                reply_markup=main_keyboard()
            )
            del WAITING[chat_id]
            return

        # обработка ввода при созданном круге (купил/продал)
        if "type" in step:
            try:
                value = float(text)
            except:
                await update.message.reply_text("Введите число")
                return

            # если ещё нет usdt в шаге — это первая цифра (USDT)
            if "usdt" not in step:
                step["usdt"] = value
                await update.message.reply_text("Сколько KZT это стоило/дали?", reply_markup=None)
                return

            # если есть usdt и нет fiat — сохраняем fiat и записываем в БД
            if "fiat" not in step:
                step["fiat"] = value
                circle_id = CURRENT_CIRCLE.get(chat_id)
                if not circle_id:
                    await update.message.reply_text("Нет активного круга, сначала создайте его", reply_markup=main_keyboard())
                    del WAITING[chat_id]
                    return

                side = "BUY" if step["type"] == "buy" else "SELL"
                cursor.execute(
                    "INSERT INTO circle_trades (circle_id, side, usdt, fiat) VALUES (?, ?, ?, ?)",
                    (circle_id, side, step["usdt"], step["fiat"])
                )
                conn.commit()

                await update.message.reply_text(
                    f"✅ Записано: {side} {step['usdt']} USDT → {step['fiat']} KZT",
                    reply_markup=circle_keyboard()
                )
                del WAITING[chat_id]
                return

    # ===== BUTTONS =====

    if text == "⭕ Создать круг":
        cursor.execute(
            "INSERT INTO circles(chat_id,created_at) VALUES(?,datetime('now'))",
            (chat_id,)
        )
        conn.commit()
        circle_id = cursor.lastrowid
        CURRENT_CIRCLE[chat_id] = circle_id
        await update.message.reply_text(
            f"⭕ Круг {circle_id} создан",
            reply_markup=circle_keyboard()
        )

    elif text == "🟢 Купил":
        WAITING[chat_id] = {"type": "buy"}
        await update.message.reply_text("Сколько USDT купил?")

    elif text == "🔴 Продал":
        WAITING[chat_id] = {"type": "sell"}
        await update.message.reply_text("Сколько USDT продал?")

    elif text == "💾 Сохранить круг":
        circle_id = CURRENT_CIRCLE.get(chat_id)
        if not circle_id:
            await update.message.reply_text("Нет активного круга")
            return
        stats = circle_stats(circle_id)
        await update.message.reply_text(
            f"⭕ Круг сохранён\n\n"
            f"Куплено: {stats[0]} USDT\n"
            f"Продано: {stats[1]} USDT\n"
            f"Прибыль: {stats[2]:.2f}\n"
            f"Доходность: {stats[3]:.2f}%"
        )
        del CURRENT_CIRCLE[chat_id]
        await update.message.reply_text("Главное меню", reply_markup=main_keyboard())

    elif text == "📚 Круги":
        rows = cursor.execute(
            "SELECT id FROM circles ORDER BY id DESC LIMIT 10"
        ).fetchall()
        if not rows:
            await update.message.reply_text("Нет кругов")
            return
        msg = "📚 Последние круги\n\n"
        for r in rows:
            stats = circle_stats(r[0])
            msg += (
                f"Круг {r[0]} | "
                f"Profit {stats[2]:.2f} | "
                f"{stats[3]:.2f}%\n"
            )
        await update.message.reply_text(msg)

    elif text == "📊 Цена":
        WAITING[chat_id] = {"price_query": True}
        kb = ReplyKeyboardMarkup([["Покупка", "Продажа"]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("Покупка или Продажа?", reply_markup=kb)

    elif text == "💳 Взять депозит":
        WAITING[chat_id] = {"deposit_action": "withdraw"}
        await update.message.reply_text("Сколько KZT вы берёте с депозита?")

    elif text == "💵 Вернуть депозит":
        WAITING[chat_id] = {"deposit_action": "return"}
        await update.message.reply_text("Сколько KZT вы возвращаете на депозит?")

    elif text == "💼 Депозит":
        total_withdraw = cursor.execute(
            "SELECT SUM(amount) FROM deposit WHERE chat_id=? AND type='withdraw'",
            (chat_id,)
        ).fetchone()[0] or 0
        total_return = cursor.execute(
            "SELECT SUM(amount) FROM deposit WHERE chat_id=? AND type='return'",
            (chat_id,)
        ).fetchone()[0] or 0
        balance = total_withdraw - total_return
        await update.message.reply_text(
            f"💼 Депозит:\n\n"
            f"💰 Взято с депозита: {total_withdraw:.2f} KZT\n"
            f"💵 Вернули: {total_return:.2f} KZT\n"
            f"⚖ Осталось вернуть: {balance:.2f} KZT",
            reply_markup=main_keyboard()
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()