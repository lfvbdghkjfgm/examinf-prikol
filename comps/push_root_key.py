#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import socket
import sys
import time
from pathlib import Path

import paramiko


DEFAULT_USERNAME = "examen"
DEFAULT_PASSWORD = "Ex"
DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 5.0
DEFAULT_WORKERS = 32
DEFAULT_KEY_PATH = r"C:\Users\aatop\.ssh\root_lp_key.pub"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connects to hosts over SSH as examen/Ex and installs the local "
            "public key into /root/.ssh/authorized_keys via sudo."
        )
    )
    parser.add_argument(
        "ips",
        nargs="*",
        help="IP addresses to process. If omitted, IPs are read from --file.",
    )
    parser.add_argument(
        "-f",
        "--file",
        default="hosts.txt",
        help="Path to a file with one IP per line. Default: hosts.txt",
    )
    parser.add_argument(
        "--key",
        default=DEFAULT_KEY_PATH,
        help=f"Path to the public key file. Default: {DEFAULT_KEY_PATH}",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"SSH port. Default: {DEFAULT_PORT}",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Per-host timeout in seconds. Default: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Maximum number of concurrent hosts. Default: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--show-errors",
        action="store_true",
        help="Print failed hosts to stderr.",
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


def load_public_key(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"Public key file not found: {path}")

    key_text = path.read_text(encoding="utf-8").strip()
    if not key_text:
        raise ValueError(f"Public key file is empty: {path}")

    return key_text


def remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("host timed out")
    return remaining


def open_ssh_client(
    ip: str,
    username: str,
    password: str,
    port: int,
    timeout: float,
) -> paramiko.SSHClient:
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


def run_sudo_command(
    client: paramiko.SSHClient,
    command: str,
    sudo_password: str,
    timeout: float,
) -> tuple[int, str, str]:
    final_command = f"sudo -S -p '' bash -lc {shlex.quote(command)}"
    stdin, stdout, stderr = client.exec_command(final_command, timeout=timeout)
    stdin.write(sudo_password + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()
    stdout_data = stdout.read().decode("utf-8", errors="replace").strip()
    stderr_data = stderr.read().decode("utf-8", errors="replace").strip()
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout_data, stderr_data


def upload_temp_key(
    client: paramiko.SSHClient,
    ip: str,
    key_text: str,
    timeout: float,
) -> str:
    remote_path = f"/tmp/root_lp_key_{ip.replace('.', '_')}_{int(time.time() * 1000)}.pub"
    sftp = client.open_sftp()
    try:
        sftp.get_channel().settimeout(timeout)
        with sftp.file(remote_path, "w") as remote_file:
            remote_file.write(key_text + "\n")
    finally:
        sftp.close()
    return remote_path


def install_key_sync(
    ip: str,
    port: int,
    timeout: float,
    key_text: str,
) -> tuple[dict[str, str] | None, str | None]:
    client: paramiko.SSHClient | None = None
    remote_key_path = ""
    deadline = time.monotonic() + timeout

    try:
        client = open_ssh_client(
            ip=ip,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD,
            port=port,
            timeout=remaining_timeout(deadline),
        )

        remote_key_path = upload_temp_key(
            client=client,
            ip=ip,
            key_text=key_text,
            timeout=remaining_timeout(deadline),
        )

        command = (
            f"install -d -m 700 /root/.ssh && "
            f"touch /root/.ssh/authorized_keys && "
            f"chmod 600 /root/.ssh/authorized_keys && "
            f"key=$(cat {shlex.quote(remote_key_path)}) && "
            f"if grep -qxF -- \"$key\" /root/.ssh/authorized_keys; then "
            f"echo already_present; "
            f"else "
            f"printf '%s\\n' \"$key\" >> /root/.ssh/authorized_keys; "
            f"echo installed; "
            f"fi && "
            f"rm -f {shlex.quote(remote_key_path)}"
        )

        exit_code, stdout_data, stderr_data = run_sudo_command(
            client=client,
            command=command,
            sudo_password=DEFAULT_PASSWORD,
            timeout=remaining_timeout(deadline),
        )

        if exit_code != 0:
            error_text = stderr_data or stdout_data or f"command exited with code {exit_code}"
            return None, error_text

        status = stdout_data.splitlines()[-1].strip() if stdout_data else "installed"
        return {"ip": ip, "status": status}, None
    except TimeoutError:
        return None, f"timed out after {timeout:.1f}s"
    except (paramiko.SSHException, paramiko.AuthenticationException, socket.timeout, OSError) as exc:
        return None, str(exc)
    finally:
        if client is not None and remote_key_path:
            try:
                stdin, stdout, stderr = client.exec_command(
                    f"rm -f {shlex.quote(remote_key_path)}",
                    timeout=max(0.5, remaining_timeout(deadline)),
                )
                stdin.close()
                stdout.channel.recv_exit_status()
            except Exception:
                pass
        if client is not None:
            client.close()


async def install_key(
    ip: str,
    port: int,
    timeout: float,
    key_text: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, str] | None, str | None]:
    async with semaphore:
        try:
            result, error = await asyncio.to_thread(
                install_key_sync,
                ip,
                port,
                timeout,
                key_text,
            )
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
    key_text: str,
    show_errors: bool,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    semaphore = asyncio.Semaphore(max(1, workers))
    tasks = [
        asyncio.create_task(install_key(ip, port, timeout, key_text, semaphore))
        for ip in ips
    ]

    for task in asyncio.as_completed(tasks):
        ip, result, error = await task
        if result is not None:
            results.append(result)
        elif show_errors and error:
            print(f"{ip}: {error}", file=sys.stderr)

    results.sort(key=lambda row: ip_sort_key(row["ip"]))
    return results


async def async_main() -> int:
    args = parse_args()

    try:
        ips = load_ips(args.ips, args.file)
        key_text = load_public_key(args.key)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    results = await iter_results(
        ips=ips,
        port=args.port,
        timeout=args.timeout,
        workers=args.workers,
        key_text=key_text,
        show_errors=args.show_errors,
    )

    json.dump(results, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
