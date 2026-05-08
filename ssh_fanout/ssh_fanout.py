#!/usr/bin/env python3
"""
Run one sudo command on many SSH hosts from a shared interactive prompt.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shlex
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import paramiko
except ImportError:  # pragma: no cover - this is a startup help path.
    print("Missing dependency: paramiko", file=sys.stderr)
    print("Install it with: python -m pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(2)


@dataclass(frozen=True)
class HostConfig:
    name: str
    host: str
    port: int
    username: str
    password: str
    sudo_password: str


@dataclass
class CommandResult:
    name: str
    host: str
    ok: bool
    exit_code: int | None = None
    output: str = ""
    error: str = ""


class HostSession:
    def __init__(
        self,
        config: HostConfig,
        strict_host_key_checking: bool,
        connect_timeout: int,
        sudo_get_pty: bool,
    ) -> None:
        self.config = config
        self.strict_host_key_checking = strict_host_key_checking
        self.connect_timeout = connect_timeout
        self.sudo_get_pty = sudo_get_pty
        self.client: paramiko.SSHClient | None = None
        self.last_error = ""
        self.lock = threading.RLock()

    @property
    def label(self) -> str:
        if self.config.name == self.config.host:
            return self.config.host
        return f"{self.config.name} ({self.config.host})"

    def connect(self) -> bool:
        with self.lock:
            self.close()
            client = paramiko.SSHClient()
            if self.strict_host_key_checking:
                client.load_system_host_keys()
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                client.connect(
                    hostname=self.config.host,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    timeout=self.connect_timeout,
                    auth_timeout=self.connect_timeout,
                    banner_timeout=self.connect_timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
            except paramiko.ssh_exception.BadAuthenticationType as exc:
                if "keyboard-interactive" not in getattr(exc, "allowed_types", []):
                    self.client = None
                    self.last_error = str(exc)
                    return False
                try:
                    client = self.connect_keyboard_interactive()
                except Exception as interactive_exc:  # noqa: BLE001 - show per-host auth problem.
                    self.client = None
                    self.last_error = f"{exc}; keyboard-interactive failed: {interactive_exc}"
                    return False
            except Exception as exc:  # noqa: BLE001 - show connection problem per host.
                self.client = None
                self.last_error = str(exc)
                return False

            self.client = client
            self.last_error = ""
            return True

    def connect_keyboard_interactive(self) -> paramiko.SSHClient:
        sock = socket.create_connection((self.config.host, self.config.port), timeout=self.connect_timeout)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = self.connect_timeout
        transport.auth_timeout = self.connect_timeout

        try:
            transport.start_client(timeout=self.connect_timeout)
            self.check_host_key(transport)

            def handler(_title: str, _instructions: str, prompt_list: list[tuple[str, bool]]) -> list[str]:
                return [self.config.password for _prompt, _show_input in prompt_list]

            transport.auth_interactive(self.config.username, handler)
            if not transport.is_authenticated():
                raise paramiko.ssh_exception.AuthenticationException("keyboard-interactive auth failed")

            client = paramiko.SSHClient()
            client._transport = transport
            return client
        except Exception:
            transport.close()
            raise

    def check_host_key(self, transport: paramiko.Transport) -> None:
        if not self.strict_host_key_checking:
            return

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        server_key = transport.get_remote_server_key()
        host_key_name = self.config.host
        if self.config.port != 22:
            host_key_name = f"[{self.config.host}]:{self.config.port}"

        system_keys = getattr(client, "_system_host_keys")
        local_keys = getattr(client, "_host_keys")
        if not (system_keys.check(host_key_name, server_key) or local_keys.check(host_key_name, server_key)):
            raise paramiko.ssh_exception.SSHException(f"Unknown or changed host key for {host_key_name}")

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def is_connected(self) -> bool:
        if self.client is None:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def ensure_connected(self) -> bool:
        if self.is_connected():
            return True
        return self.connect()

    def run_sudo(self, command: str, cwd: str | None, timeout: int) -> CommandResult:
        with self.lock:
            if not self.ensure_connected() or self.client is None:
                return CommandResult(
                    name=self.config.name,
                    host=self.config.host,
                    ok=False,
                    error=f"SSH connection failed: {self.last_error}",
                )

            remote_command = command
            if cwd:
                remote_command = f"cd {shlex.quote(cwd)} && {command}"
            sudo_command = "sudo -S -p '' bash -lc " + shlex.quote(remote_command)
            if self.sudo_get_pty:
                sudo_command = (
                    "stty -echo 2>/dev/null; "
                    + sudo_command
                    + "; rc=$?; stty echo 2>/dev/null; exit $rc"
                )

            try:
                stdin, stdout, stderr = self.client.exec_command(sudo_command, get_pty=self.sudo_get_pty)
                if self.sudo_get_pty:
                    time.sleep(0.1)
                stdin.write(self.config.sudo_password + "\n")
                stdin.flush()
                try:
                    stdin.channel.shutdown_write()
                except Exception:
                    pass

                channel = stdout.channel
                started_at = time.monotonic()
                stdout_chunks: list[bytes] = []
                stderr_chunks: list[bytes] = []

                while not channel.exit_status_ready():
                    self._drain_channel(channel, stdout_chunks, stderr_chunks)
                    if timeout > 0 and time.monotonic() - started_at > timeout:
                        channel.close()
                        return CommandResult(
                            name=self.config.name,
                            host=self.config.host,
                            ok=False,
                            error=f"Command timed out after {timeout} seconds",
                        )
                    time.sleep(0.05)

                self._drain_channel(channel, stdout_chunks, stderr_chunks)
                exit_code = channel.recv_exit_status()
                output = b"".join(stdout_chunks).decode("utf-8", errors="replace")
                err = b"".join(stderr_chunks).decode("utf-8", errors="replace")
                return CommandResult(
                    name=self.config.name,
                    host=self.config.host,
                    ok=exit_code == 0,
                    exit_code=exit_code,
                    output=output,
                    error=err,
                )
            except Exception as exc:  # noqa: BLE001 - keep the REPL alive per host.
                self.close()
                self.last_error = str(exc)
                return CommandResult(
                    name=self.config.name,
                    host=self.config.host,
                    ok=False,
                    error=f"Command failed: {exc}",
                )

    @staticmethod
    def _drain_channel(channel: paramiko.Channel, stdout_chunks: list[bytes], stderr_chunks: list[bytes]) -> None:
        while channel.recv_ready():
            stdout_chunks.append(channel.recv(65535))
        while channel.recv_stderr_ready():
            stderr_chunks.append(channel.recv_stderr(65535))


def load_config(path: Path) -> tuple[list[HostConfig], dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    defaults = {
        "username": data.get("username", "examen"),
        "password": data.get("password", "Ex"),
        "sudo_password": data.get("sudo_password", data.get("password", "Ex")),
        "port": int(data.get("port", 22)),
    }

    hosts: list[HostConfig] = []
    for item in data.get("hosts", []):
        if isinstance(item, str):
            host_data: dict[str, Any] = {"host": item}
        elif isinstance(item, dict):
            host_data = item
        else:
            raise ValueError(f"Unsupported host entry: {item!r}")

        host = str(host_data.get("host") or host_data.get("ip") or "").strip()
        if not host:
            raise ValueError(f"Host entry has no host/ip field: {item!r}")

        name = str(host_data.get("name") or host)
        hosts.append(
            HostConfig(
                name=name,
                host=host,
                port=int(host_data.get("port", defaults["port"])),
                username=str(host_data.get("username", defaults["username"])),
                password=str(host_data.get("password", defaults["password"])),
                sudo_password=str(host_data.get("sudo_password", defaults["sudo_password"])),
            )
        )

    if not hosts:
        raise ValueError("Config contains no hosts")
    return hosts, data


def print_help() -> None:
    print(
        """
Commands:
  <linux command>       run through sudo on every connected host
  :hosts                show connection state
  :cd /path             set remote working directory for following commands
  :cd                   clear remote working directory
  :timeout N            set command timeout in seconds; 0 means no limit
  :reconnect            reconnect to every host
  :help                 show this help
  :exit                 quit
""".strip()
    )


def connect_all(sessions: list[HostSession], workers: int) -> None:
    print(f"Connecting to {len(sessions)} host(s)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(session.connect): session for session in sessions}
        for future in concurrent.futures.as_completed(futures):
            session = futures[future]
            ok = future.result()
            if ok:
                print(f"[ok]   {session.label}")
            else:
                print(f"[fail] {session.label}: {session.last_error}")


def print_hosts(sessions: list[HostSession]) -> None:
    for session in sessions:
        if session.is_connected():
            print(f"[ok]   {session.label}")
        else:
            detail = f": {session.last_error}" if session.last_error else ""
            print(f"[down] {session.label}{detail}")


def run_on_all(sessions: list[HostSession], command: str, cwd: str | None, timeout: int, workers: int) -> None:
    active_sessions = [session for session in sessions if session.is_connected()]
    skipped_sessions = [session for session in sessions if not session.is_connected()]

    if skipped_sessions:
        print(f"Skipping {len(skipped_sessions)} disconnected host(s). Use :hosts or :reconnect for details.")
    if not active_sessions:
        print("No connected hosts.")
        return

    print(f"Running on {len(active_sessions)} connected host(s): {command}")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(active_sessions)))
    try:
        futures = {
            executor.submit(session.run_sudo, command, cwd, timeout): session
            for session in active_sessions
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            status = "ok" if result.ok else "fail"
            code = "" if result.exit_code is None else f" exit={result.exit_code}"
            print(f"\n===== [{status}{code}] {result.name} ({result.host}) =====")

            body = (result.output or "") + (result.error or "")
            if body:
                print(body, end="" if body.endswith("\n") else "\n")
            else:
                print("(no output)")
    except KeyboardInterrupt:
        print("\nInterrupted. Closing active SSH channels...")
        for session in active_sessions:
            session.close()
        for future in futures:
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    print()


def repl(sessions: list[HostSession], command_timeout: int, workers: int) -> None:
    cwd: str | None = None
    timeout = command_timeout
    print_help()
    while True:
        prompt_cwd = cwd or "~"
        try:
            command = input(f"sudo-all:{prompt_cwd}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not command:
            continue
        if command in {":exit", ":quit"}:
            return
        if command == ":help":
            print_help()
            continue
        if command == ":hosts":
            print_hosts(sessions)
            continue
        if command.startswith(":timeout "):
            try:
                timeout = max(0, int(command.split(maxsplit=1)[1]))
            except ValueError:
                print("Usage: :timeout 120")
                continue
            print(f"Command timeout set to {timeout} second(s)")
            continue
        if command == ":reconnect":
            connect_all(sessions, workers)
            continue
        if command == ":cd":
            cwd = None
            print("Remote working directory cleared")
            continue
        if command.startswith(":cd "):
            cwd = command[4:].strip()
            print(f"Remote working directory set to: {cwd}")
            continue

        run_on_all(sessions, command, cwd, timeout, workers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sudo commands on many SSH hosts.")
    parser.add_argument("-c", "--config", default="hosts.json", help="Path to JSON config file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    try:
        hosts, raw_config = load_config(config_path)
    except Exception as exc:  # noqa: BLE001 - startup should be concise.
        print(f"Cannot load config {config_path}: {exc}", file=sys.stderr)
        return 2

    strict_host_key_checking = bool(raw_config.get("strict_host_key_checking", False))
    connect_timeout = int(raw_config.get("connect_timeout", 10))
    command_timeout = int(raw_config.get("command_timeout", 120))
    sudo_get_pty = bool(raw_config.get("sudo_get_pty", False))
    workers = min(len(hosts), int(raw_config.get("parallelism", len(hosts))))
    workers = max(workers, 1)

    sessions = [
        HostSession(
            host,
            strict_host_key_checking=strict_host_key_checking,
            connect_timeout=connect_timeout,
            sudo_get_pty=sudo_get_pty,
        )
        for host in hosts
    ]

    try:
        connect_all(sessions, workers)
        repl(sessions, command_timeout=command_timeout, workers=workers)
    finally:
        for session in sessions:
            session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
