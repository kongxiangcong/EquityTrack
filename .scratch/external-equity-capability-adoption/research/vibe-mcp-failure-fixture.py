from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("crash", "timeout", "malformed"))
    args = parser.parse_args()
    sys.stdin.readline()
    if args.mode == "crash":
        raise SystemExit(23)
    if args.mode == "timeout":
        time.sleep(30)
        return
    sys.stdout.write("this-is-not-json\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
