#!/bin/bash

# ============================
# Настройки
# ============================
REPO_URL="https://github.com/username/repo.git"  # ссылка на твой GitHub
BOT_DIR="$HOME/bot"                               # путь, где будет бот
SCREEN_NAME="mybot"                               # имя screen
PYTHON_CMD="python3"                              

# ============================
# 1️⃣ Создать папку, если нет
# ============================
mkdir -p "$BOT_DIR"
cd "$BOT_DIR" || exit

# ============================
# 2️⃣ Клонировать репозиторий или обновить
# ============================
if [ -d ".git" ]; then
    echo "Обновляем репозиторий..."
    git pull origin main
else
    echo "Клонируем репозиторий..."
    git clone "$REPO_URL" .
fi

# ============================
# 3️⃣ Создать виртуальное окружение, если нет
# ============================
if [ ! -d "venv" ]; then
    echo "Создаём виртуальное окружение..."
    $PYTHON_CMD -m venv venv
fi

# ============================
# 4️⃣ Активируем виртуальное окружение
# ============================
source venv/bin/activate

# ============================
# 5️⃣ Обновляем pip и ставим зависимости
# ============================
pip install --upgrade pip
pip install -r requirements.txt

# ============================
# 6️⃣ Завершаем старый screen (если есть)
# ============================
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Завершаем старую сессию $SCREEN_NAME..."
    screen -S "$SCREEN_NAME" -X quit
fi

# ============================
# 7️⃣ Запускаем бота в новой screen сессии
# ============================
echo "Запускаем бота в screen $SCREEN_NAME..."
screen -dmS "$SCREEN_NAME" bash -c "source venv/bin/activate; $PYTHON_CMD bot.py >> bot.log 2>&1"

echo "Бот запущен в фоне. Логи -> $BOT_DIR/bot.log"
echo "Подключиться к screen: screen -r $SCREEN_NAME"