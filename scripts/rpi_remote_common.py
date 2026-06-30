#!/usr/bin/env python3
"""Shared helpers for Raspberry Pi deploy/start/stop scripts."""

from __future__ import annotations

import csv
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICES_CSV = REPO_ROOT / "rpi_app" / "devices.csv"
ENV_FILE = REPO_ROOT / ".env"

# Each canvas role maps to a fixed pygame display index on the Pi.
ROLE_DISPLAY = {"left": 0, "right": 1}

# Each canvas role maps to a fixed physical HDMI connector. player_panel.py
# selects the matching display by this name (stable across reboots), and the
# display index above is only a fallback if the name cannot be matched.
ROLE_OUTPUT = {"left": "HDMI-A-1", "right": "HDMI-A-2"}


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


def service_name(role: str) -> str:
    """Return the systemd user-unit name for a canvas role (e.g. ``left``)."""

    return f"robot-game-{role}.service"


def user_systemctl(ssh, args: str, check: bool = True) -> tuple[int, str, str]:
    """Run ``systemctl --user <args>`` for the login user over SSH.

    Non-login SSH sessions do not inherit the user manager's bus address, so we
    export ``XDG_RUNTIME_DIR``/``DBUS_SESSION_BUS_ADDRESS`` (derived from the
    current uid) before invoking ``systemctl --user``.
    """

    prefix = (
        'export XDG_RUNTIME_DIR="/run/user/$(id -u)"; '
        'export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"; '
    )
    cmd = "bash -lc " + shlex.quote(prefix + f"systemctl --user {args}")
    return run_remote(ssh, cmd, check=check)


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


def parse_indices(tokens: list[str] | None, all_indices: list[int]) -> list[int]:
    """Resolve ``--devices`` tokens to an ordered, de-duplicated index list.

    Each token is either a single index (``3``) or an inclusive range
    (``1-6``). ``None`` selects every device found in ``devices.csv``.
    """

    if not tokens:
        return all_indices

    resolved: list[int] = []
    for token in tokens:
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            resolved.extend(range(start, end + 1) if start <= end else range(start, end - 1, -1))
        else:
            resolved.append(int(token))

    seen: set[int] = set()
    ordered: list[int] = []
    for index in resolved:
        if index not in seen:
            seen.add(index)
            ordered.append(index)
    return ordered


def resolve_targets(indices: list[int]) -> list[tuple[int, Target]]:
    """Map device indices to ``Target`` rows from ``devices.csv``."""

    rows = load_devices()
    by_index = {int(row["index"]): row for row in rows}

    targets: list[tuple[int, Target]] = []
    for index in indices:
        row = by_index.get(index)
        if row is None:
            valid = ", ".join(f"{r['index']}:{r['hostname']}" for r in rows)
            raise ValueError(f"Unknown device index {index}. Known devices: {valid}")
        ip = row.get("ip")
        targets.append((index, Target(host=ip or row["hostname"], ip=ip)))
    return targets


def select_targets(tokens: list[str] | None) -> list[tuple[int, Target]]:
    """Resolve ``--devices`` tokens straight to ``(index, Target)`` pairs.

    With no tokens this selects every device in ``devices.csv``, mirroring the
    "default to the whole fleet" behaviour of ``deploy_app.py``.
    """

    all_indices = sorted(int(row["index"]) for row in load_devices())
    return resolve_targets(parse_indices(tokens, all_indices))


def run_on_devices(
    targets: list[tuple[int, Target]],
    worker: Callable[[object, Callable[[str], None]], None],
    *,
    username: str,
    password: str,
    port: int = 22,
    summary_label: str = "Done",
) -> None:
    """Run ``worker`` against each device concurrently and report a summary.

    ``worker(ssh, log)`` performs the per-device action; it should call ``log``
    for progress and raise on failure. Each device is connected, serviced, and
    closed independently so one failure does not stop the others. Buffered log
    lines are printed as one block per device. Exits with status 1 if any device
    failed.
    """

    print_lock = Lock()
    results: dict[int, bool] = {}

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(_run_one, index, target, worker, username, password, port): index
            for index, target in targets
        }

        for future in as_completed(futures):
            index = futures[future]
            ok, lines = future.result()
            results[index] = ok
            with print_lock:
                print("\n".join(lines))

    succeeded = sorted(i for i, ok in results.items() if ok)
    failed = sorted(i for i, ok in results.items() if not ok)
    print()
    print(f"{summary_label}. Succeeded: {succeeded or 'none'}. Failed: {failed or 'none'}.")
    if failed:
        raise SystemExit(1)


def _run_one(
    index: int,
    target: Target,
    worker: Callable[[object, Callable[[str], None]], None],
    username: str,
    password: str,
    port: int,
) -> tuple[bool, list[str]]:
    """Connect to one device, run ``worker``, and return ``(ok, log_lines)``."""

    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(f"[{index}:{target.host}] {message}")

    try:
        ssh = connect_ssh(target.host, username, password, port=port)
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED to connect: {exc}")
        return False, lines

    try:
        worker(ssh, log)
        return True, lines
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED: {exc}")
        return False, lines
    finally:
        ssh.close()
