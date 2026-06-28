#!/usr/bin/env python3
"""Install systemd *user* services so each Pi auto-starts its canvas on boot.

For every selected device this script writes two user units
(``robot-game-left.service`` / ``robot-game-right.service``) into
``~/.config/systemd/user``, enables lingering so the user manager runs without a
login session, then enables and (re)starts both services. Each unit restarts
automatically two seconds after it exits, so a crashed or closed panel comes
back on its own.

Devices are taken from ``devices.csv`` by index and serviced concurrently, the
same way ``deploy_app.py`` works.
"""

from __future__ import annotations

import argparse
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from deploy_app import parse_indices, resolve_targets
from rpi_remote_common import (
    ROLE_DISPLAY,
    ROLE_OUTPUT,
    Target,
    connect_ssh,
    load_devices,
    resolve_credentials,
    run_remote,
    service_name,
    user_systemctl,
)

RESTART_DELAY_S = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and enable canvas auto-start systemd user services on Raspberry Pis over SSH.",
    )
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to configure, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    parser.add_argument("--wayland-display", default="wayland-0", help="Remote WAYLAND_DISPLAY value.")
    return parser.parse_args()


def build_unit(
    remote_dir: str, python_bin: str, wayland_display: str, role: str, display_idx: int, output: str
) -> str:
    """Return the systemd unit text for one canvas role.

    The compositor may not be ready the instant the user manager starts at boot,
    so ``Restart=always`` keeps retrying every ``RESTART_DELAY_S`` seconds until
    the Wayland socket is available (and after any later crash/close).
    ``StartLimitIntervalSec=0`` disables systemd's start-rate limiter so the
    retries never trip the "start request repeated too quickly" failure while
    waiting for the graphics stack to come up.

    ``--output`` pins the panel to a physical HDMI connector; ``--display`` is a
    fallback index if the connector name cannot be matched. ``--require-outputs``
    makes the panel wait for every connector to come up before opening its
    window, avoiding the boot-time race that mis-assigns fullscreen surfaces.
    """

    app = f"{remote_dir}/rpi_app/player_panel.py"
    require = ",".join(ROLE_OUTPUT[r] for r in ROLE_DISPLAY)
    return (
        "[Unit]\n"
        f"Description=Robot game canvas ({role})\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n"
        "StartLimitIntervalSec=0\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"Environment=WAYLAND_DISPLAY={wayland_display}\n"
        "Environment=SDL_VIDEODRIVER=wayland\n"
        "Environment=SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0\n"
        f"WorkingDirectory={remote_dir}/rpi_app\n"
        f"ExecStart={python_bin} {app} --role {role} --output {output} "
        f"--require-outputs {require} --display {display_idx}\n"
        "Restart=always\n"
        f"RestartSec={RESTART_DELAY_S}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def enable_linger(ssh, username: str, password: str) -> None:
    """Enable lingering for ``username`` so user services run without a login.

    ``sudo -S`` reads the password from stdin; on hosts with passwordless sudo
    the piped password is simply ignored.
    """

    cmd = f"sudo -S -p '' loginctl enable-linger {shlex.quote(username)}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdin.write(password + "\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"enable-linger failed ({code}).\nSTDOUT:\n{out}\nSTDERR:\n{err}")


def configure_one(
    index: int,
    target: Target,
    username: str,
    password: str,
    port: int,
    remote_dir: str,
    wayland_display: str,
) -> tuple[bool, list[str]]:
    """Install, enable, and start both canvas services on a single device.

    Returns whether the pass succeeded along with buffered log lines so the
    caller can print each device's output as one uninterrupted block.
    """

    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(f"[{index}:{target.host}] {message}")

    try:
        ssh = connect_ssh(target.host, username, password, port=port)
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED to connect: {exc}")
        return False, lines

    try:
        home = run_remote(ssh, "echo $HOME")[1].strip()
        python_bin = run_remote(ssh, "command -v python3")[1].strip()
        if not python_bin:
            raise RuntimeError("python3 not found on PATH.")
        unit_dir = f"{home}/.config/systemd/user"

        log("Enabling user lingering...")
        enable_linger(ssh, username, password)

        log(f"Writing unit files to {unit_dir}...")
        run_remote(ssh, f"mkdir -p {shlex.quote(unit_dir)}")
        with ssh.open_sftp() as sftp:
            for role, display_idx in ROLE_DISPLAY.items():
                content = build_unit(
                    remote_dir, python_bin, wayland_display, role, display_idx, ROLE_OUTPUT[role]
                )
                remote_path = f"{unit_dir}/{service_name(role)}"
                with sftp.open(remote_path, "w") as handle:
                    handle.write(content)

        names = " ".join(service_name(role) for role in ROLE_DISPLAY)
        log("Reloading and enabling services...")
        user_systemctl(ssh, "daemon-reload")
        user_systemctl(ssh, f"enable {names}")

        log("Starting services...")
        user_systemctl(ssh, f"restart {names}")
        log("Configured. Services will auto-start on boot.")
        return True, lines
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED: {exc}")
        return False, lines
    finally:
        ssh.close()


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    all_indices = sorted(int(row["index"]) for row in load_devices())
    indices = parse_indices(args.devices, all_indices)
    targets = resolve_targets(indices)

    print(f"Configuring {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets))

    print_lock = Lock()
    results: dict[int, bool] = {}

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(
                configure_one,
                index,
                target,
                username,
                password,
                args.port,
                args.remote_dir,
                args.wayland_display,
            ): index
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
    print(f"Done. Succeeded: {succeeded or 'none'}. Failed: {failed or 'none'}.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
