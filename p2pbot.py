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

# ================== DB ==================
conn = sqlite3.connect("exchange.db", check_same_thread=False)
cursor = conn.cursor()

# Таблица сделок
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

# Настройки уведомлений
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY
)
""")

# Таблица депозита
cursor.execute("""
CREATE TABLE IF NOT EXISTS deposit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    amount REAL,
    type TEXT,  -- 'withdraw' или 'return'
    created_at TEXT
)
""")
conn.commit()

# ================== STATE ==================
WAITING = {}

# ================== UI ==================
def get_keyboard(chat_id: int):
    keyboard = ReplyKeyboardMarkup(
        [
            ["📊 Цена", "➕ BUY", "➖ SELL"],
            ["📄 История", "💰 Прибыль"],
            ["📈 График", "📤 Экспорт"],
            ["💳 Взять депозит", "💵 Вернуть депозит", "💼 Депозит"],  # добавили кнопку депозита
        ],
        resize_keyboard=True
    )
    return keyboard

# ================== BINANCE ==================
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
    items = r.json()["data"]

    offers = []
    for item in items:
        price = float(item["adv"]["price"])
        nick = item["advertiser"]["nickName"]
        # безопасно получаем bankName
        if item["adv"].get("tradeMethods"):
            bank = item["adv"]["tradeMethods"][0].get("bankName", "—")
        else:
            bank = "—"

        min_amount = float(item["adv"]["minSingleTransAmount"])
        max_amount = float(item["adv"]["maxSingleTransAmount"])
        offers.append((price, nick, bank, min_amount, max_amount))

    offers.sort(key=lambda x: x[0])
    return offers

# ================== График прибыли ==================
def build_profit_chart():
    chat_ids = (YOUR_CHAT_ID, FRIEND_CHAT_ID)
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
        WHERE chat_id IN (?, ?)
        GROUP BY day
        ORDER BY day
    """, chat_ids).fetchall()

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

# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR IGNORE INTO settings (chat_id) VALUES (?)", (chat_id,))
    conn.commit()

    await update.message.reply_text(
        "🤖 IT_Exchange запущен",
        reply_markup=get_keyboard(chat_id)
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    chat_ids = (YOUR_CHAT_ID, FRIEND_CHAT_ID)

    # ====== STEP INPUT ======
    if chat_id in WAITING:
        step = WAITING[chat_id]

        # ===== депозит =====
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
                reply_markup=get_keyboard(chat_id)
            )
            del WAITING[chat_id]
            return

        # ===== сделки BUY/SELL =====
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

    # ====== Кнопки ======
    if text == "📊 Цена":
        offers = get_usdt_kzt_full()
        msg = "📊 Лучшие предложения USDT/KZT:\n\n"
        for price, nick, bank, min_amt, max_amt in offers:
            msg += f"💰 {price:.2f} KZT | 🏦 {bank} | 👤 {nick} | Сумма: {min_amt}-{max_amt} KZT\n"
        await update.message.reply_text(msg)

    elif text in ("➕ BUY", "➖ SELL"):
        WAITING[chat_id] = {
            "side": "BUY" if "BUY" in text else "SELL",
            "quote": "KZT"
        }
        await update.message.reply_text("Сколько USDT?")

    elif text == "📄 История":
        rows = cursor.execute(
            "SELECT side, base_amount, quote_amount, quote, price, created_at "
            "FROM trades WHERE chat_id IN (?, ?) ORDER BY id DESC LIMIT 5",
            chat_ids
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
            "SELECT SUM(quote_amount) FROM trades WHERE chat_id IN (?, ?) AND side='BUY'",
            chat_ids
        ).fetchone()[0] or 0
        sell = cursor.execute(
            "SELECT SUM(quote_amount) FROM trades WHERE chat_id IN (?, ?) AND side='SELL'",
            chat_ids
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
            "FROM trades WHERE chat_id IN (?, ?)",
            chat_ids
        ).fetchall()
        with open("trades.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Side", "Base", "Quote", "Base Amount", "Quote Amount", "Price", "Time"]
            )
            for r in rows:
                writer.writerow(r)
        await update.message.reply_document(open("trades.csv", "rb"))

    elif text == "📈 График":
        path = build_profit_chart()
        if not path:
            await update.message.reply_text("Пока нет данных для графика")
            return
        await update.message.reply_photo(
            photo=open(path, "rb"),
            caption="📈 Прибыль по дням (KZT)"
        )

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
        reply_markup=get_keyboard(chat_id)
    )


# ================== MAIN ==================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    global YOUR_CHAT_ID, FRIEND_CHAT_ID
    YOUR_CHAT_ID = 822462684
    FRIEND_CHAT_ID = 6042777779
    main()
