#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import sys
import time
from pathlib import Path

import paramiko


CREDENTIALS = (
    ("student", "15761576"),
    ("examen", "Ex"),
)
CHECK_USERS = ("student", "examen")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROMPT_RE = re.compile(r"([A-Za-z0-9._-]+)@([^\s:@]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Checks SSH access for a list of IPs. For each reachable host, "
            "tries student/15761576 first, then examen/Ex."
        )
    )
    parser.add_argument(
        "ips",
        nargs="*",
        help="IP addresses to check. If omitted, IPs are read from --file.",
    )
    parser.add_argument(
        "-f",
        "--file",
        default="hosts.txt",
        help="Path to a file with one IP per line. Default: hosts.txt",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=22,
        help="SSH port. Default: 22",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=5.0,
        help="Per-host timeout in seconds. Default: 5",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=32,
        help="Maximum number of concurrent SSH checks. Default: 32",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--show-errors",
        action="store_true",
        help="Print unreachable/authentication errors to stderr.",
    )
    return parser.parse_args()


def load_ips(ips: list[str], file_path: str) -> list[str]:
    if ips:
        return [ip.strip() for ip in ips if ip.strip()]

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"IP list file not found: {path}")

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def open_ssh_client(ip: str, username: str, password: str, port: int, timeout: float) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ip,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
        auth_timeout=timeout,
        banner_timeout=timeout,
    )
    return client


def run_command(client: paramiko.SSHClient, command: str, timeout: float) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdout_data = stdout.read().decode("utf-8", errors="replace").strip()
    stderr_data = stderr.read().decode("utf-8", errors="replace").strip()
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout_data, stderr_data


def remote_user_exists(client: paramiko.SSHClient, username: str, timeout: float) -> bool:
    exit_code, _, _ = run_command(client, f"id -u {username} >/dev/null 2>&1", timeout)
    return exit_code == 0


def remote_prompt_host(client: paramiko.SSHClient, timeout: float) -> str:
    commands = (
        "hostname -s 2>/dev/null",
        "hostname 2>/dev/null",
        "uname -n 2>/dev/null",
    )

    for command in commands:
        exit_code, stdout_data, _ = run_command(client, command, timeout)
        if exit_code == 0 and stdout_data:
            return stdout_data.split()[0]

    return ""


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r", "")


def extract_prompt_host(text: str, expected_user: str) -> str:
    matches = PROMPT_RE.findall(strip_ansi(text))
    for user, host in reversed(matches):
        if user == expected_user:
            return host
    return ""


def remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("host timed out")
    return remaining


def student_prompt_host_via_sudo(
    client: paramiko.SSHClient,
    sudo_password: str,
    deadline: float,
) -> str:
    channel = client.invoke_shell(width=200, height=24)
    buffer = ""
    password_sent = False

    try:
        channel.settimeout(remaining_timeout(deadline))

        warmup_deadline = min(deadline, time.monotonic() + 1.0)
        while time.monotonic() < warmup_deadline:
            if channel.recv_ready():
                buffer += channel.recv(65535).decode("utf-8", errors="replace")
            else:
                time.sleep(0.05)

        channel.send("sudo su student\n")

        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("host timed out")

            if channel.recv_ready():
                buffer += channel.recv(65535).decode("utf-8", errors="replace")
                prompt_host = extract_prompt_host(buffer, "student")
                if prompt_host:
                    return prompt_host

                cleaned = strip_ansi(buffer).lower()
                if not password_sent and ("password:" in cleaned or "[sudo]" in cleaned):
                    channel.send(sudo_password + "\n")
                    password_sent = True

                if any(
                    marker in cleaned
                    for marker in (
                        "su: user student does not exist",
                        "unknown user",
                        "authentication failure",
                        "is not in the sudoers file",
                        "sorry, try again",
                    )
                ):
                    return ""
            else:
                time.sleep(0.05)
    finally:
        channel.close()


def probe_host_sync(ip: str, port: int, timeout: float) -> tuple[list[object] | None, str | None]:
    first_success_client: paramiko.SSHClient | None = None
    first_success_password = ""
    first_success_username = ""
    errors: list[str] = []
    deadline = time.monotonic() + timeout

    try:
        for username, password in CREDENTIALS:
            try:
                client = open_ssh_client(
                    ip,
                    username,
                    password,
                    port,
                    remaining_timeout(deadline),
                )
                if first_success_client is None:
                    first_success_client = client
                    first_success_username = username
                    first_success_password = password
                else:
                    client.close()
            except paramiko.AuthenticationException:
                errors.append(f"{username}: authentication failed")
            except TimeoutError:
                return None, f"timed out after {timeout:.1f}s"
            except (paramiko.SSHException, socket.timeout, OSError) as exc:
                errors.append(f"{username}: {exc}")
                break

        if first_success_client is None:
            return None, "; ".join(errors) if errors else "connection failed"

        student_exists = remote_user_exists(
            first_success_client,
            CHECK_USERS[0],
            remaining_timeout(deadline),
        )
        examen_exists = remote_user_exists(
            first_success_client,
            CHECK_USERS[1],
            remaining_timeout(deadline),
        )
        prompt_host = remote_prompt_host(
            first_success_client,
            remaining_timeout(deadline),
        )
        if first_success_username == "examen" and student_exists:
            try:
                student_prompt_host = student_prompt_host_via_sudo(
                    first_success_client,
                    first_success_password,
                    deadline,
                )
            except (TimeoutError, paramiko.SSHException, socket.timeout, OSError):
                student_prompt_host = ""
            if student_prompt_host:
                prompt_host = student_prompt_host
        return [ip, student_exists, examen_exists, prompt_host], None
    except TimeoutError:
        return None, f"timed out after {timeout:.1f}s"
    finally:
        if first_success_client is not None:
            first_success_client.close()


async def probe_host(
    ip: str,
    port: int,
    timeout: float,
    semaphore: asyncio.Semaphore,
) -> tuple[str, list[object] | None, str | None]:
    async with semaphore:
        try:
            result, error = await asyncio.to_thread(probe_host_sync, ip, port, timeout)
            return ip, result, error
        except Exception as exc:  # pragma: no cover - defensive fallback
            return ip, None, f"unexpected error: {exc}"


def ip_sort_key(ip: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ip.split("."))


async def iter_results(
    ips: list[str],
    port: int,
    timeout: float,
    workers: int,
    show_errors: bool,
) -> list[list[object]]:
    results: list[list[object]] = []
    semaphore = asyncio.Semaphore(max(1, workers))
    tasks = [
        asyncio.create_task(probe_host(ip, port, timeout, semaphore))
        for ip in ips
    ]

    for task in asyncio.as_completed(tasks):
        ip, result, error = await task
        if result is not None:
            results.append(result)
        elif show_errors and error:
            print(f"{ip}: {error}", file=sys.stderr)

    results.sort(key=lambda row: ip_sort_key(str(row[0])))
    return results


async def async_main() -> int:
    args = parse_args()

    try:
        ips = load_ips(args.ips, args.file)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    results = await iter_results(
        ips=ips,
        port=args.port,
        timeout=args.timeout,
        workers=args.workers,
        show_errors=args.show_errors,
    )

    json.dump(results, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
