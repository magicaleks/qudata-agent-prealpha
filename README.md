# QuData Agent

GPU-оптимизированный агент для управления Docker контейнерами с поддержкой NVIDIA GPU, автоматической настройкой SSH и мониторингом ресурсов.

## 🚀 Быстрая установка

### One-line установка (рекомендуется)

```bash
curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent-prealpha/main/install.sh | sudo bash -s YOUR_API_KEY
```

### Альтернативная установка

```bash
# Скачать скрипт
wget https://raw.githubusercontent.com/magicaleks/qudata-agent-prealpha/main/install.sh

# Запустить установку
sudo bash install.sh YOUR_API_KEY
```
а
## 📋 Что устанавливает скрипт

1. **Системные зависимости**: git, curl, wget, ethtool, dmidecode и др.
2. **Python 3.10+**: если не установлен
3. **Docker**: последняя версия через официальный скрипт
4. **NVIDIA драйверы** (если обнаружен GPU): nvidia-driver-535
5. **NVIDIA Container Toolkit**: для поддержки GPU в Docker
6. **QuData Agent**: клонирование репозитория и установка зависимостей
7. **Systemd сервис**: автоматический запуск агента

## ⚙️ Требования

- **ОС**: Ubuntu 22.04 (рекомендуется)
- **Права**: root/sudo
- **Интернет**: для скачивания пакетов
- **GPU** (опционально): NVIDIA GPU для GPU-инстансов

## 🔧 Управление агентом

### Просмотр логов (real-time)
```bash
# Journald логи
sudo journalctl -u qudata-agent -f

# Файловые логи
sudo tail -f /opt/qudata-agent/logs.txt
```

### Статус агента
```bash
sudo systemctl status qudata-agent
```

### Остановка/запуск/перезапуск
```bash
sudo systemctl stop qudata-agent
sudo systemctl start qudata-agent
sudo systemctl restart qudata-agent
```

### Обновление агента
```bash
cd /opt/qudata-agent
sudo git pull origin main
sudo systemctl restart qudata-agent
```

## 📡 API Endpoints

### `GET /ping`
Проверка доступности агента

**Ответ:**
```json
{
  "ok": true,
  "data": null
}
```

### `POST /instances`
Создание нового контейнера

**Запрос:**
```json
{
  "image": "nvidia/cuda:12.6.1-base-ubuntu22.04",
  "image_tag": "latest",
  "storage_gb": 10,
  "env_variables": {
    "QUDATA_CPU_CORES": "4",
    "QUDATA_MEMORY_GB": "8",
    "QUDATA_GPU_COUNT": "1"
  },
  "ports": {
    "8080": "auto",
    "3000": "3000"
  },
  "command": null,
  "ssh_enabled": true
}
```

**Ответ:**
```json
{
  "ok": true,
  "data": {
    "success": true,
    "ports": {
      "22": "1025",
      "8080": "32768",
      "3000": "3000"
    }
  }
}
```

### `GET /instances?logs=true`
Получить состояние инстанса (с логами опционально)

**Ответ:**
```json
{
  "ok": true,
  "data": {
    "instance_id": "uuid",
    "container_id": "docker_id",
    "status": "running",
    "allocated_ports": {"22": "1025"},
    "logs": "container logs..."
  }
}
```

### `PUT /instances`
Управление контейнером (stop/start/restart)

**Запрос:**
```json
{
  "action": "stop"
}
```

### `DELETE /instances`
Удаление контейнера

### SSH Endpoints

#### `POST /ssh`
Добавить SSH ключ в контейнер

**Запрос:**
```json
{
  "ssh_pubkey": "ssh-rsa AAAAB3NzaC1yc2EA... user@host"
}
```

#### `DELETE /ssh`
Удалить SSH ключ из контейнера

**Запрос:**
```json
{
  "ssh_pubkey": "ssh-rsa AAAAB3NzaC1yc2EA... user@host"
}
```

#### `GET /ssh`
Получить список SSH ключей в контейнере

**Ответ:**
```json
{
  "ok": true,
  "data": {
    "keys": [
      "ssh-rsa AAAAB3NzaC1yc2EA...",
      "ssh-ed25519 AAAAC3NzaC1lZDI1..."
    ]
  }
}
```

## 🔐 SSH подключение к контейнеру

1. Создайте инстанс с `ssh_enabled: true`
2. Добавьте свой публичный ключ через `POST /ssh`
3. Подключитесь: `ssh root@<agent_ip> -p <ssh_port>`

Пример:
```bash
# Получить порт SSH
curl http://agent_ip:port/instances | jq '.data.allocated_ports["22"]'

# Добавить SSH ключ
curl -X POST http://agent_ip:port/ssh \
  -H "Content-Type: application/json" \
  -d '{"ssh_pubkey": "ssh-rsa AAAAB3... user@host"}'

# Подключиться
ssh root@agent_ip -p 1025
```

## 📊 Мониторинг

Агент автоматически отправляет статистику каждые 3 секунды:
- **CPU utilization** (%)
- **RAM utilization** (%)
- **Container status** (running/paused/error)

Статистика также отправляется при каждом действии управления (stop/start/restart).

## 🏗️ Структура проекта

```
qudata-agent/
├── main.py                 # Точка входа
├── requirements.txt        # Python зависимости
├── install.sh             # Скрипт установки
├── secret_key.json        # API ключ (создается при установке)
├── logs.txt               # Логи агента
└── src/
    ├── client/            # HTTP клиент для API
    ├── server/            # Falcon ASGI сервер
    ├── service/           # Бизнес-логика
    │   ├── instances.py   # Управление контейнерами
    │   ├── ssh_setup.py   # Настройка SSH в контейнерах
    │   ├── ssh_keys.py    # Управление SSH ключами
    │   ├── gpu_info.py    # Сбор информации о GPU
    │   ├── health.py      # Проверка здоровья системы
    │   └── system_check.py # Проверка системных требований
    ├── storage/           # Хранилище данных
    └── utils/             # Утилиты
```

## 🔄 Автоматические возможности

### SSH Setup (фоновый)
При создании контейнера с `ssh_enabled: true` агент автоматически:
- Устанавливает `openssh-server`
- Настраивает SSH daemon
- Создает `.ssh/authorized_keys`
- Запускает SSH сервер

Процесс выполняется в фоне, ответ возвращается сразу.

### Синхронизация состояния
Каждые 30 секунд агент автоматически синхронизирует свое состояние с Docker:
- Проверяет существование контейнеров
- Обновляет статусы
- Очищает несуществующие контейнеры

### Graceful Shutdown
При остановке агента (SIGTERM/SIGINT):
- Корректно завершает все процессы
- Сохраняет состояние
- Останавливает HTTP сервер

## 🐛 Отладка

### Проверка статуса Docker
```bash
sudo systemctl status docker
sudo docker ps -a
```

### Проверка NVIDIA GPU
```bash
nvidia-smi
sudo docker run --rm --gpus all nvidia/cuda:12.6.1-base-ubuntu22.04 nvidia-smi
```

### Просмотр последних ошибок
```bash
sudo journalctl -u qudata-agent -n 100 --no-pager
```

### Ручной запуск (для отладки)
```bash
cd /opt/qudata-agent
sudo python3 main.py YOUR_API_KEY
```

## 🔥 Удаление

```bash
# Остановка и удаление сервиса
sudo systemctl stop qudata-agent
sudo systemctl disable qudata-agent
sudo rm /etc/systemd/system/qudata-agent.service
sudo systemctl daemon-reload

# Удаление файлов
sudo rm -rf /opt/qudata-agent
```

## 📝 Примечания

- API ключ хранится в `/opt/qudata-agent/secret_key.json` с правами 600
- Контейнеры без команды запускаются с `tail -f /dev/null` (idle mode)
- При stop контейнер останавливается, но не удаляется (можно запустить снова)
- Образы Docker с тегом в имени обрабатываются корректно (например `nvidia/cuda:12.6.1-base-ubuntu22.04`)

## 🛠️ Поддерживаемые действия с контейнерами

| Действие | Описание |
|----------|----------|
| `create` | Создание и запуск контейнера |
| `stop` | Остановка контейнера (данные сохраняются) |
| `start` | Запуск остановленного контейнера |
| `restart` | Перезапуск контейнера |
| `delete` | Полное удаление контейнера |

## 📄 Лицензия

MIT

## 🤝 Поддержка

При возникновении проблем:
1. Проверьте логи: `sudo journalctl -u qudata-agent -f`
2. Проверьте Docker: `sudo docker ps -a`
3. Проверьте системные требования
4. Создайте issue на GitHub
