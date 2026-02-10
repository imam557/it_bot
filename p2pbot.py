import matplotlib.pyplot as plt
from datetime import datetime

import requests
import sqlite3
import csv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8503792556:AAE14E9hzN3ppo9ONcXVc2_cfNLZ9tsFe-Q"
CHECK_INTERVAL = 60

# ================== DB ==================
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
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    notify INTEGER DEFAULT 1
)
""")

conn.commit()

# ================== STATE ==================
WAITING = {}
LAST_PRICE = {}

# ================== UI ==================
def get_keyboard(chat_id: int):
    notify = cursor.execute(
        "SELECT notify FROM settings WHERE chat_id=?",

        (chat_id,)
    ).fetchone()

    notify_text = "🔔 Уведомления: ВКЛ" if notify and notify[0] else "🔕 Уведомления: ВЫКЛ"

    keyboard = ReplyKeyboardMarkup(
    [
        ["📊 Цена", "➕ BUY", "➖ SELL"],
        ["📄 История", "💰 Прибыль"],
        ["📈 График", "📤 Экспорт"],
    ],
    resize_keyboard=True
    )
    return keyboard

# ================== BINANCE ==================
def get_usdt_kzt():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "asset": "USDT",
        "fiat": "KZT",
        "tradeType": "BUY",
        "page": 1,
        "rows": 5
    }
    r = requests.post(url, json=payload, timeout=10)
    items = r.json()["data"]
    best = min(items, key=lambda x: float(x["adv"]["price"]))
    return float(best["adv"]["price"])


def build_profit_chart(chat_id):
    rows = cursor.execute("""
        SELECT 
            date(created_at) as day,
            SUM(
                CASE 
                    WHEN side='SELL' THEN quote_amount
                    WHEN side='BUY' THEN -quote_amount
                END
            ) as profit
        FROM trades
        WHERE chat_id=?
        GROUP BY day
        ORDER BY day
    """, (chat_id,)).fetchall()

    if not rows:
        return None

    days = [r[0] for r in rows]
    profits = [r[1] for r in rows]

    plt.figure(figsize=(8, 4))
    plt.plot(days, profits, marker="o")
    plt.axhline(0)
    plt.title("Прибыль по дням (KZT)")
    plt.xlabel("Дата")
    plt.ylabel("Прибыль")
    plt.grid(True)
    plt.tight_layout()

    path = "profit_chart.png"
    plt.savefig(path)
    plt.close()

    return path


# ================== WATCHER ==================
async def watcher(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id

    notify = cursor.execute(
        "SELECT notify FROM settings WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    if not notify or notify[0] == 0:
        return

    price = get_usdt_kzt()
    last = LAST_PRICE.get(chat_id)

    if last and price != last:
        diff = price - last
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚨 USDT/KZT изменился: {diff:+.2f}\nТекущая цена: {price}"
        )

    LAST_PRICE[chat_id] = price

# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    cursor.execute(
        "INSERT OR IGNORE INTO settings (chat_id) VALUES (?)",
        (chat_id,)
    )
    conn.commit()

    context.job_queue.run_repeating(
        watcher,
        interval=CHECK_INTERVAL,
        first=5,
        chat_id=chat_id
    )

    await update.message.reply_text(
        "🤖 IT_Exchange запущен",
        reply_markup=get_keyboard(chat_id)
    )

    

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # ====== STEP INPUT ======
    if chat_id in WAITING:
        step = WAITING[chat_id]

        try:
            value = float(text)
        except:
            await update.message.reply_text("Введите число")
            return

        if "base_amount" not in step:
            step["base_amount"] = value
            await update.message.reply_text("Сколько получил/отдал в KZT?")
            return

        step["quote_amount"] = value
        step["price"] = step["quote_amount"] / step["base_amount"]

        cursor.execute(
            """INSERT INTO trades 
            (chat_id, side, base, quote, base_amount, quote_amount, price, created_at)
            VALUES (?, ?, 'USDT', ?, ?, ?, ?, datetime('now'))""",
            (
                chat_id,
                step["side"],
                step["quote"],
                step["base_amount"],
                step["quote_amount"],
                step["price"]
            )
        )
        conn.commit()

        await update.message.reply_text(
            f"✅ Сделка сохранена\n"
            f"{step['side']} USDT/{step['quote']}\n"
            f"USDT: {step['base_amount']}\n"
            f"{step['quote']}: {step['quote_amount']}\n"
            f"Курс: {step['price']:.2f}",
            reply_markup=get_keyboard(chat_id)
        )

        del WAITING[chat_id]
        return

    # ====== BUTTONS ======
    if text == "📊 Цена":
        price = get_usdt_kzt()
        await update.message.reply_text(f"USDT/KZT: {price}")

    elif text in ("➕ BUY", "➖ SELL"):
        WAITING[chat_id] = {
            "side": "BUY" if "BUY" in text else "SELL",
            "quote": "KZT"
        }
        await update.message.reply_text("Сколько USDT?")

    elif text == "📄 История":
        rows = cursor.execute(
            "SELECT side, base_amount, quote_amount, quote, price, created_at "
            "FROM trades WHERE chat_id=? ORDER BY id DESC LIMIT 5",
            (chat_id,)
        ).fetchall()

        if not rows:
            await update.message.reply_text("История пуста")
            return

        msg = "📄 Последние сделки:\n\n"
        for r in rows:
            msg += f"{r[5][:16]} | {r[0]} {r[1]} USDT → {r[2]} {r[3]} | {r[4]:.2f}\n"

        await update.message.reply_text(msg)

    elif text == "💰 Прибыль":
        buy = cursor.execute(
            "SELECT SUM(quote_amount) FROM trades WHERE chat_id=? AND side='BUY'",
            (chat_id,)
        ).fetchone()[0] or 0

        sell = cursor.execute(
            "SELECT SUM(quote_amount) FROM trades WHERE chat_id=? AND side='SELL'",
            (chat_id,)
        ).fetchone()[0] or 0

        await update.message.reply_text(
            f"💰 Итог:\n\n"
            f"Потрачено: {buy:.2f}\n"
            f"Получено: {sell:.2f}\n"
            f"Прибыль: {sell - buy:+.2f}"
        )

    elif text == "📤 Экспорт":
        rows = cursor.execute(
            "SELECT side, base, quote, base_amount, quote_amount, price, created_at "
            "FROM trades WHERE chat_id=?",
            (chat_id,)
        ).fetchall()

        with open("trades.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Side", "Base", "Quote", "Base Amount", "Quote Amount", "Price", "Time"]
            )
            for r in rows:
                writer.writerow(r)

        await update.message.reply_document(open("trades.csv", "rb"))

    elif text.startswith("🔔") or text.startswith("🔕"):
        current = cursor.execute(
            "SELECT notify FROM settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()[0]

        new = 0 if current else 1
        cursor.execute(
            "UPDATE settings SET notify=? WHERE chat_id=?",
            (new, chat_id)
        )
        conn.commit()

        await update.message.reply_text(
            "Настройка обновлена",
            reply_markup=get_keyboard(chat_id)
        )
    elif text == "📈 График":
        path = build_profit_chart(chat_id)

        if not path:
            await update.message.reply_text("Пока нет данных для графика")
            return

        await update.message.reply_photo(
            photo=open(path, "rb"),
            caption="📈 Прибыль по дням (KZT)"
    )

# ================== MAIN ==================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
