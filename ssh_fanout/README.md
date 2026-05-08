# SSH fanout sudo terminal

Инструмент открывает SSH-сессии ко всем хостам из `hosts.json` и дает общий prompt: вводишь команду один раз, она выполняется через `sudo` на каждом компьютере.

## Установка

```powershell
cd C:\Users\aatop\Documents\vs\ssh_fanout
python -m pip install -r requirements.txt
```

## Настройка

Открой `hosts.json` и замени примерные IP-адреса на реальные:

```json
{
  "username": "examen",
  "password": "Ex",
  "sudo_password": "Ex",
  "command_timeout": 120,
  "sudo_get_pty": false,
  "hosts": [
    "192.168.1.10",
    "192.168.1.11"
  ]
}
```

Можно задавать имя или отдельный порт для конкретной машины:

```json
{
  "name": "class-01",
  "host": "192.168.1.10",
  "port": 22
}
```

## Запуск

```powershell
python .\ssh_fanout.py
```

Примеры внутри prompt:

```text
sudo-all:~> whoami
sudo-all:~> apt update
sudo-all:~> systemctl restart nginx
sudo-all:~> :hosts
sudo-all:~> :timeout 300
sudo-all:~> :cd /var/log
sudo-all:/var/log> ls -lah
sudo-all:/var/log> :exit
```

`command_timeout: 0` означает без ограничения времени. Лучше держать число секунд, например `120`, чтобы зависшая команда не блокировала общий терминал.

`sudo_get_pty: false` не печатает sudo-пароль в вывод. Если на каких-то машинах sudo ругается `sorry, you must have a tty`, поставь `sudo_get_pty: true`.

Пароль в конфиге хранится открытым текстом, поэтому держи файл только в защищенной админской папке. Для более строгой схемы лучше перейти на SSH-ключи и `NOPASSWD` для нужных команд.
