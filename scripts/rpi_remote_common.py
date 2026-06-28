#!/usr/bin/env python3
"""Shared helpers for Raspberry Pi deploy/start/stop scripts."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICES_CSV = REPO_ROOT / "rpi_app" / "devices.csv"
ENV_FILE = REPO_ROOT / ".env"


@dataclass(frozen=True)
class Target:
    host: str
    ip: str | None


def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_devices() -> list[dict[str, str]]:
    if not DEVICES_CSV.exists():
        raise FileNotFoundError(f"devices.csv not found at {DEVICES_CSV}")

    rows: list[dict[str, str]] = []
    with DEVICES_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def resolve_target(device: str | None, host: str | None, ip: str | None) -> Target:
    def build_target(row: dict[str, str]) -> Target:
        row_ip = row.get("ip")
        return Target(host=row_ip or row["hostname"], ip=row_ip)

    if host:
        return Target(host=host, ip=ip)
    if ip:
        return Target(host=ip, ip=ip)

    rows = load_devices()
    if not device:
        raise ValueError("Provide --device, --host, or --ip.")

    if device.isdigit():
        as_int = int(device)
        for row in rows:
            if int(row.get("index", "-1")) == as_int:
                return build_target(row)

        suffix = f"-{as_int:02d}"
        for row in rows:
            if row.get("hostname", "").endswith(suffix):
                return build_target(row)

    for row in rows:
        if row.get("hostname") == device:
            return build_target(row)

    valid = ", ".join(f"{r['index']}:{r['hostname']}" for r in rows)
    raise ValueError(f"Could not resolve device '{device}'. Known devices: {valid}")


def resolve_credentials(username: str | None, password: str | None) -> tuple[str, str]:
    env = load_dotenv()

    user = username or env.get("PI_USERNAME")
    pw = password or env.get("PI_PASSWORD")

    if not user or not pw:
        raise ValueError("Missing credentials. Set .env values PI_USERNAME/PI_PASSWORD or pass --username/--password.")

    return user, pw


def connect_ssh(host: str, username: str, password: str, port: int = 22):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required. Install with: pip install paramiko") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=username, password=password, timeout=10)
    return client


def run_remote(ssh, command: str, check: bool = True) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(command)
    _ = stdin
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"Remote command failed ({code}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return code, out, err


def mkdirs_remote_sftp(sftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else f"/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def upload_tree(sftp, local_root: Path, remote_root: str, include: Iterable[Path]) -> None:
    mkdirs_remote_sftp(sftp, remote_root)

    for source in include:
        source = source.resolve()
        rel = source.relative_to(local_root.resolve())
        remote_path = f"{remote_root}/{rel.as_posix()}"

        if source.is_dir():
            mkdirs_remote_sftp(sftp, remote_path)
            for local_file in source.rglob("*"):
                if local_file.is_dir():
                    continue
                file_rel = local_file.relative_to(local_root.resolve())
                remote_file = f"{remote_root}/{file_rel.as_posix()}"
                mkdirs_remote_sftp(sftp, str(Path(remote_file).parent).replace("\\", "/"))
                sftp.put(str(local_file), remote_file)
        else:
            mkdirs_remote_sftp(sftp, str(Path(remote_path).parent).replace("\\", "/"))
            sftp.put(str(source), remote_path)
