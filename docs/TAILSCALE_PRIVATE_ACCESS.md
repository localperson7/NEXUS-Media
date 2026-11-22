# Приватный HTTPS-доступ к NEXUS Media для iPhone через Tailscale Serve

Этот документ описывает безопасный доступ к вашему локальному серверу **NEXUS Media** с реального **iPhone** без публикации в открытый интернет, без проброса портов на роутере и без изменения правил брандмауэра.

> **Критическое правило безопасности:**
> Используйте **ТОЛЬКО** `tailscale serve` (приватный доступ внутри вашего личного tailnet).
> **НИКОГДА** не включайте `tailscale funnel`, чтобы не открывать медиасервер в публичный интернет.

---

## Шаг 0. Проверка и установка Tailscale (требуется подтверждение владельца)

По результатам проверки на этой системе CachyOS пакет `tailscale` **не установлен**.
После вашего решения установить Tailscale:

```fish
# 1. Установка на CachyOS / Arch Linux:
sudo pacman -S tailscale

# 2. Включение системного демона tailscaled:
sudo systemctl enable --now tailscaled

# 3. Авторизация этого ПК в вашем личном tailnet:
sudo tailscale up
```

На **iPhone**: установите официальное приложение **Tailscale** из App Store и войдите в тот же аккаунт tailnet.

---

## Шаг 1. Запуск единого production-сервера NEXUS Media (только на `127.0.0.1`)

Фронтенд (`frontend/dist`) и API FastAPI + SSE теперь работают на **одном origin** (`http://127.0.0.1:8000`).
Рекомендуется задать личный код доступа `NEXUS_MEDIA_ACCESS_TOKEN` для дополнительной защиты поверх tailnet:

```fish
# Сборка актуального production-фронтенда (если были изменения):
cd ~/Projects/NEXUS-Media/frontend
npm run build

# Запуск единого сервера FastAPI (строго на localhost 127.0.0.1:8000):
cd ~/Projects/NEXUS-Media/backend
source .venv/bin/activate.fish
set -x NEXUS_MEDIA_ACCESS_TOKEN "придумайте-длинный-личный-код"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> Сервер **не слушает** `0.0.0.0` и недоступен даже из локальной Wi-Fi сети напрямую — трафик принимает только локальный прокси Tailscale Serve.

---

## Шаг 2. Включение приватного HTTPS через Tailscale Serve

Во втором окне терминала `fish` (убедитесь, что в панели Tailscale Admin Console включён MagicDNS и HTTPS Certificates):

```fish
# Включить приватный HTTPS-прокси внутри tailnet (порт 443 -> локальный 127.0.0.1:8000):
tailscale serve --https=443 http://127.0.0.1:8000
```

После выполнения команды Tailscale выведет ваш приватный HTTPS-адрес вида:
`https://<имя-хоста>.<ваш-tailnet>.ts.net/`

Проверить активную конфигурацию (убедиться, что Funnel выключен):
```fish
tailscale serve status
```

---

## Шаг 3. Установка PWA на реальный iPhone (Safari)

1. Включите **Tailscale VPN** на iPhone.
2. Откройте в **Safari** адрес `https://<имя-хоста>.<ваш-tailnet>.ts.net/`.
3. Если задан `NEXUS_MEDIA_ACCESS_TOKEN`, введите ваш код доступа — сервер установит защищённый cookie (`HttpOnly; SameSite=Strict; Secure`) на 30 дней.
4. Нажмите в нижней панели Safari кнопку **Поделиться** → **На экран «Домой»** → **Добавить**.
5. Запустите **NEXUS Media** с экрана «Домой» в полноэкранном режиме (`standalone`).

---

## Шаг 4. Как отключить удалённый доступ

Чтобы немедленно закрыть доступ через Tailscale Serve:

```fish
# Сбросить все правила Tailscale Serve:
tailscale serve reset

# Проверить, что правил не осталось:
tailscale serve status
```

Также можно остановить сам процесс `uvicorn` нажатием `Ctrl+C` в терминале.
