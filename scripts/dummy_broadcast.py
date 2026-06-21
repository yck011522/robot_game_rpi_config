#!/usr/bin/env python3
"""Send a minimal UDP game-state payload for Raspberry Pi UI tests."""

from __future__ import annotations

import argparse
import json
import socket
import time


STATES = ["daydreaming", "idle", "tutorial", "play", "conclusion"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Broadcast simple game-state packets over UDP.")
    parser.add_argument("--dest", default="192.168.0.255", help="UDP destination address.")
    parser.add_argument("--port", type=int, default=49200, help="UDP destination port.")
    parser.add_argument("--hz", type=float, default=5.0, help="Send rate in packets per second.")
    parser.add_argument("--duration", type=int, default=0, help="Optional run duration in seconds; 0 means forever.")
    parser.add_argument("--team", default="A", help="Team id to include in payload.")
    parser.add_argument("--joint", type=int, default=1, help="Joint id to include in payload.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    interval = 1.0 / max(0.1, args.hz)
    started = time.monotonic()
    seq = 0
    timer_s = 90

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"Broadcasting to {args.dest}:{args.port} at {args.hz:.2f} Hz")

    try:
        while True:
            if args.duration > 0 and (time.monotonic() - started) >= args.duration:
                print("Duration elapsed; stopping broadcaster.")
                break

            state = STATES[(seq // int(max(1, args.hz) * 6)) % len(STATES)]
            if seq % max(1, int(args.hz)) == 0:
                timer_s = 90 if timer_s <= 0 else timer_s - 1

            payload = {
                "v": 1,
                "seq": seq,
                "ts_wall_ns": time.time_ns(),
                "team": args.team,
                "joint": args.joint,
                "game_state": state,
                "timer_s": timer_s,
            }

            sock.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), (args.dest, args.port))
            if seq % max(1, int(args.hz)) == 0:
                print(f"seq={seq} state={state} timer={timer_s}")

            seq += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
