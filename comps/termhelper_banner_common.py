from __future__ import annotations

import argparse
import json
import posixpath
import shlex
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import paramiko


DEFAULT_USERNAME = "examen"
DEFAULT_PASSWORD = "Ex"
DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 10
DEFAULT_WORKERS = 16

REMOTE_BANNER_DIR = "/usr/local/share/termhelper/header_logo"
REMOTE_BANNER_PATH = f"{REMOTE_BANNER_DIR}/fimoztech"
REMOTE_CONFIG_DIR = "/etc/termhelper.d"
REMOTE_CONFIG_PATH = f"{REMOTE_CONFIG_DIR}/zz-fimoztech-banner"
LEGACY_CONFIG_PATH = f"{REMOTE_CONFIG_DIR}/fimoztech"
STATE_DIR = "/var/lib/fimoztech-banner"
STATE_FILE = f"{STATE_DIR}/state.json"
STATE_CONFIG_BACKUP = f"{STATE_DIR}/zz-fimoztech-banner.bak"
STATE_LEGACY_CONFIG_BACKUP = f"{STATE_DIR}/fimoztech-legacy.bak"
STATE_BANNER_BACKUP = f"{STATE_DIR}/fimoztech.bak"


class BannerError(RuntimeError):
    pass


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str


def q(value: str) -> str:
    return shlex.quote(value)


def parse_hosts(hosts: Iterable[str], hosts_file: str | None) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    def add(host: str) -> None:
        host = host.strip()
        if not host or host.startswith("#") or host in seen:
            return
        seen.add(host)
        items.append(host)

    for host in hosts:
        for piece in host.split(","):
            add(piece)

    if hosts_file:
        for line in Path(hosts_file).read_text(encoding="utf-8").splitlines():
            add(line)

    if not items:
        raise BannerError("Ne peredany IP-adresa. Ukazhi ih argumentami ili cherez --hosts-file.")

    return items


def build_common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("hosts", nargs="*", help="IP-adresa ili hosty. Mozhno perechislit cherez probel ili zapyatuyu.")
    parser.add_argument("--hosts-file", help="Fail so spiskom IP-adresov/hostov, po odnomu na stroku.")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"SSH-polzovatel. Po umolchaniyu: {DEFAULT_USERNAME}")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Parol SSH-polzovatelya.")
    parser.add_argument(
        "--sudo-password",
        default=None,
        help="Parol dlya sudo. Esli ne ukazan, budet ispolzovan parol SSH-polzovatelya.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"SSH-port. Po umolchaniyu: {DEFAULT_PORT}")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout podklyucheniya i komand v sekundah. Po umolchaniyu: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Skolko hostov obrabatyvat parallelno. Po umolchaniyu: {DEFAULT_WORKERS}",
    )
    return parser


class RemoteBannerManager:
    def __init__(
        self,
        host: str,
        *,
        username: str,
        password: str,
        sudo_password: str | None,
        port: int,
        timeout: int,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.sudo_password = sudo_password or password
        self.port = port
        self.timeout = timeout
        self.client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            banner_timeout=self.timeout,
            auth_timeout=self.timeout,
            channel_timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        self.client = client

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self) -> "RemoteBannerManager":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def run(self, command: str, *, sudo: bool = False, check: bool = True) -> CommandResult:
        if self.client is None:
            raise BannerError("SSH-sessiya ne otkryta.")

        final_command = command
        if sudo:
            final_command = f"sudo -S -p '' bash -lc {q(command)}"

        stdin, stdout, stderr = self.client.exec_command(final_command, timeout=self.timeout, get_pty=False)
        if sudo:
            stdin.write(self.sudo_password + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()
        else:
            stdin.close()

        try:
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
        except (TimeoutError, socket.timeout) as exc:
            raise BannerError(f"{self.host}: komanda zavisla: {command}") from exc

        exit_code = stdout.channel.recv_exit_status()
        result = CommandResult(final_command, exit_code, out, err)

        if check and exit_code != 0:
            message = err.strip() or out.strip() or f"Komanda zavershilas s kodom {exit_code}"
            raise BannerError(f"{self.host}: {message}")

        return result

    def exists(self, path: str, *, sudo: bool = False) -> bool:
        result = self.run(f"test -e {q(path)}", sudo=sudo, check=False)
        return result.exit_code == 0

    def upload(self, local_path: str, remote_path: str) -> None:
        if self.client is None:
            raise BannerError("SSH-sessiya ne otkryta.")
        sftp = self.client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def upload_text(self, text: str, remote_path: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            self.upload(tmp_path, remote_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def ensure_backup_state(self) -> None:
        self.run(f"install -d -m 755 {q(REMOTE_BANNER_DIR)} {q(REMOTE_CONFIG_DIR)}", sudo=True)
        self.run(f"install -d -m 700 {q(STATE_DIR)}", sudo=True)

        if self.exists(STATE_FILE, sudo=True):
            return

        config_existed = self.exists(REMOTE_CONFIG_PATH, sudo=True)
        legacy_config_existed = self.exists(LEGACY_CONFIG_PATH, sudo=True)
        banner_existed = self.exists(REMOTE_BANNER_PATH, sudo=True)

        if config_existed:
            self.run(f"cp -a {q(REMOTE_CONFIG_PATH)} {q(STATE_CONFIG_BACKUP)}", sudo=True)
        else:
            self.run(f"rm -f {q(STATE_CONFIG_BACKUP)}", sudo=True)

        if legacy_config_existed:
            self.run(f"cp -a {q(LEGACY_CONFIG_PATH)} {q(STATE_LEGACY_CONFIG_BACKUP)}", sudo=True)
        else:
            self.run(f"rm -f {q(STATE_LEGACY_CONFIG_BACKUP)}", sudo=True)

        if banner_existed:
            self.run(f"cp -a {q(REMOTE_BANNER_PATH)} {q(STATE_BANNER_BACKUP)}", sudo=True)
        else:
            self.run(f"rm -f {q(STATE_BANNER_BACKUP)}", sudo=True)

        state = {
            "managed_paths": {
                "banner": REMOTE_BANNER_PATH,
                "config": REMOTE_CONFIG_PATH,
            },
            "banner_existed": banner_existed,
            "config_existed": config_existed,
            "legacy_config_existed": legacy_config_existed,
        }
        remote_tmp = f"/tmp/fimoztech-state-{self.username}.json"
        self.upload_text(json.dumps(state, ensure_ascii=False, indent=2), remote_tmp)
        try:
            self.run(f"install -m 600 {q(remote_tmp)} {q(STATE_FILE)}", sudo=True)
        finally:
            self.run(f"rm -f {q(remote_tmp)}", check=False)

    def install_banner(self, local_banner_path: str) -> None:
        banner_path = Path(local_banner_path)
        if not banner_path.is_file():
            raise BannerError(f"Lokalnyi fail bannera ne naiden: {banner_path}")

        self.ensure_backup_state()

        remote_tmp = posixpath.join("/tmp", f"fimoztech-banner-{self.username}.txt")
        config_text = f"HEADER_LOGO={REMOTE_BANNER_PATH}\n"
        remote_config_tmp = posixpath.join("/tmp", f"fimoztech-config-{self.username}.txt")

        self.upload(str(banner_path), remote_tmp)
        self.upload_text(config_text, remote_config_tmp)
        try:
            self.run(f"install -m 644 {q(remote_tmp)} {q(REMOTE_BANNER_PATH)}", sudo=True)
            self.run(f"install -m 644 {q(remote_config_tmp)} {q(REMOTE_CONFIG_PATH)}", sudo=True)
            self.run(f"rm -f {q(LEGACY_CONFIG_PATH)}", sudo=True, check=False)
        finally:
            self.run(f"rm -f {q(remote_tmp)} {q(remote_config_tmp)}", check=False)

    def read_state(self) -> dict | None:
        if not self.exists(STATE_FILE, sudo=True):
            return None
        result = self.run(f"cat {q(STATE_FILE)}", sudo=True)
        return json.loads(result.stdout)

    def restore_banner(self) -> None:
        state = self.read_state()

        if state is None:
            self.run(
                f"rm -f {q(REMOTE_CONFIG_PATH)} {q(LEGACY_CONFIG_PATH)} {q(REMOTE_BANNER_PATH)}",
                sudo=True,
                check=False,
            )
            return

        if state.get("config_existed"):
            self.run(f"install -m 644 {q(STATE_CONFIG_BACKUP)} {q(REMOTE_CONFIG_PATH)}", sudo=True)
        else:
            self.run(f"rm -f {q(REMOTE_CONFIG_PATH)}", sudo=True, check=False)

        if state.get("legacy_config_existed"):
            self.run(f"install -m 644 {q(STATE_LEGACY_CONFIG_BACKUP)} {q(LEGACY_CONFIG_PATH)}", sudo=True)
        else:
            self.run(f"rm -f {q(LEGACY_CONFIG_PATH)}", sudo=True, check=False)

        if state.get("banner_existed"):
            self.run(f"install -m 644 {q(STATE_BANNER_BACKUP)} {q(REMOTE_BANNER_PATH)}", sudo=True)
        else:
            self.run(f"rm -f {q(REMOTE_BANNER_PATH)}", sudo=True, check=False)

        self.run(f"rm -rf {q(STATE_DIR)}", sudo=True, check=False)
