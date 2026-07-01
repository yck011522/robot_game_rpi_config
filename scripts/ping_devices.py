#!/usr/bin/env python3
"""Ping Raspberry Pi devices listed in devices.csv.

By default this checks every configured device. Use --devices to restrict to one
or more indices (single values or ranges, e.g. 1 3 5-6).
"""

from __future__ import annotations

import argparse
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from rpi_remote_common import load_devices, parse_indices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ping Raspberry Pi devices from devices.csv.")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to ping, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--count", type=int, default=1, help="Ping echo count per host (default: 1).")
    parser.add_argument("--timeout-ms", type=int, default=1000, help="Timeout per ping in ms (default: 1000).")
    return parser.parse_args()


def build_ping_command(host: str, count: int, timeout_ms: int) -> list[str]:
    system = platform.system().lower()
    if "windows" in system:
        return ["ping", "-n", str(count), "-w", str(timeout_ms), host]

    timeout_s = max(1, int(round(timeout_ms / 1000)))
    return ["ping", "-c", str(count), "-W", str(timeout_s), host]


def ping_one(index: int, hostname: str, ip: str, count: int, timeout_ms: int) -> tuple[int, bool, str]:
    command = build_ping_command(ip, count=count, timeout_ms=timeout_ms)
    result = subprocess.run(command, capture_output=True, text=True)
    ok = result.returncode == 0

    status = "OK" if ok else "FAILED"
    line = f"[{index}:{hostname} {ip}] {status}"
    if not ok and result.stderr.strip():
        line += f" | stderr: {result.stderr.strip()}"
    return index, ok, line


def main() -> None:
    args = parse_args()

    rows = load_devices()
    all_indices = sorted(int(row["index"]) for row in rows)
    selected = parse_indices(args.devices, all_indices)

    by_index = {int(row["index"]): row for row in rows}
    targets: list[tuple[int, str, str]] = []
    for index in selected:
        row = by_index.get(index)
        if row is None:
            valid = ", ".join(str(i) for i in all_indices)
            raise SystemExit(f"Unknown device index {index}. Known indices: {valid}")
        targets.append((index, row["hostname"], row["ip"]))

    print(f"Pinging {len(targets)} device(s): " + ", ".join(f"{i}:{ip}" for i, _, ip in targets))

    results: dict[int, bool] = {}
    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(ping_one, index, hostname, ip, args.count, args.timeout_ms): index
            for index, hostname, ip in targets
        }

        for future in as_completed(futures):
            index, ok, line = future.result()
            results[index] = ok
            print(line)

    succeeded = sorted(i for i, ok in results.items() if ok)
    failed = sorted(i for i, ok in results.items() if not ok)
    print()
    print(f"Ping complete. Succeeded: {succeeded or 'none'}. Failed: {failed or 'none'}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
