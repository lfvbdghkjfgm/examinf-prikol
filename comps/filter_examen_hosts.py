from __future__ import annotations

import argparse
import concurrent.futures as cf
import ipaddress
import re
import sys
from pathlib import Path

import paramiko


DEFAULT_USERNAME = "examen"
DEFAULT_PASSWORD = "Ex"
DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 5
DEFAULT_WORKERS = 32

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return True


def add_host(hosts: list[str], seen: set[str], value: str) -> None:
    value = value.strip()
    if not value or value.startswith("#") or value in seen:
        return
    if not is_valid_ipv4(value):
        return
    seen.add(value)
    hosts.append(value)


def parse_host_text(text: str) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        ips = IPV4_RE.findall(line)
        if ips:
            for ip in ips:
                add_host(hosts, seen, ip)
            continue

        for chunk in re.split(r"[\s,;]+", line):
            add_host(hosts, seen, chunk)

    return hosts


def load_hosts(cli_hosts: list[str], hosts_file: str | None) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    for host in cli_hosts:
        for chunk in re.split(r"[\s,;]+", host):
            add_host(hosts, seen, chunk)

    if hosts_file:
        text = Path(hosts_file).read_text(encoding="utf-8", errors="replace")
        for host in parse_host_text(text):
            add_host(hosts, seen, host)

    if not hosts:
        raise ValueError("Не найдено ни одного корректного IPv4-адреса.")

    return hosts


def can_login(host: str, username: str, password: str, port: int, timeout: int) -> bool:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        stdin, stdout, stderr = client.exec_command("whoami", timeout=timeout, get_pty=False)
        stdin.close()
        result = stdout.read().decode("utf-8", errors="replace").strip()
        stdout.channel.recv_exit_status()
        return result == username
    except Exception:
        return False
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Проверяет список IP-адресов и выводит только те, где работает SSH-вход "
            "под пользователем examen с паролем Ex."
        )
    )
    parser.add_argument(
        "hosts",
        nargs="*",
        help="IP-адреса. Можно перечислить через пробел, запятую или точку с запятой.",
    )
    parser.add_argument(
        "--hosts-file",
        help="Файл со списком IP или любым текстом, из которого можно вытащить IPv4-адреса, например вывод nmap.",
    )
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"Логин SSH. По умолчанию: {DEFAULT_USERNAME}")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Пароль SSH.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"SSH-порт. По умолчанию: {DEFAULT_PORT}")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Таймаут подключения в секундах. По умолчанию: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Количество параллельных проверок. По умолчанию: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--output",
        help="Файл, в который сохранить найденные IP-адреса. Если не указан, выводятся в stdout.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать ход проверки в stderr.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        hosts = load_hosts(args.hosts, args.hosts_file)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2

    matched: list[str] = []

    max_workers = max(1, min(args.workers, len(hosts)))

    with cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_host = {
            executor.submit(can_login, host, args.username, args.password, args.port, args.timeout): host
            for host in hosts
        }

        for future in cf.as_completed(future_to_host):
            host = future_to_host[future]
            ok = False
            try:
                ok = future.result()
            except Exception:
                ok = False

            if args.verbose:
                status = "OK" if ok else "FAIL"
                print(f"[{host}] {status}", file=sys.stderr, flush=True)

            if ok:
                matched.append(host)

    matched.sort(key=lambda value: tuple(int(part) for part in value.split(".")))
    output_text = "\n".join(matched)
    if output_text:
        output_text += "\n"

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(output_text)

    if args.verbose:
        print(f"Найдено: {len(matched)} из {len(hosts)}", file=sys.stderr, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
