#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from afterimage.contracts.hashing import canonical_sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--out", type=Path, default=Path("evidence/submission"))
    args = parser.parse_args()
    payload = json.loads(args.summary.read_text(encoding="utf-8"))
    digest = canonical_sha256(payload)
    target = args.out / f"session-{payload['session_id']}-{digest[:12]}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"sha256": digest, "payload": payload}
    target.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
