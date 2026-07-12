from __future__ import annotations

import argparse
import time
from pathlib import Path

from trading_platform import ProductionCompositionRoot
from trading_platform.web_server import LocalChartWorkspaceServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--web-root", type=Path, default=Path("web/dist"))
    args = parser.parse_args()
    root = ProductionCompositionRoot(args.data_root)
    server = LocalChartWorkspaceServer(root.facade, args.web_root, args.security_id, args.snapshot_id)
    print(server.start(), flush=True)
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        server.close(); root.close()


if __name__ == "__main__":
    main()
