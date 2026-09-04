#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from afterimage.evidence.export import evidence_core, evidence_core_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--out", type=Path, default=Path("evidence/submission"))
    args = parser.parse_args()
    payload = json.loads(args.summary.read_text(encoding="utf-8"))
    digest = evidence_core_hash(payload)
    target = args.out / f"session-{payload['session_id']}-{digest[:12]}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema": "afterimage-evidence-envelope-v1",
        "evidence_core_sha256": digest,
        "evidence_core": evidence_core(payload),
        "run_record": payload,
    }
    target.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
