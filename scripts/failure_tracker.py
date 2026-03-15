#!/usr/bin/env python3
"""CLI helper for managing import failure counts in a JSON file.

Called from import-new.sh with arguments via sys.argv — never via string
interpolation — so filenames with single quotes, shell metacharacters, or
other special characters are handled safely.

Usage:
    python3 scripts/failure_tracker.py get   <json_path> <filename>
    python3 scripts/failure_tracker.py set   <json_path> <filename> <count>
    python3 scripts/failure_tracker.py clear <json_path> <filename>
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def cmd_get(json_path: Path, filename: str) -> None:
    data = _load(json_path)
    print(data.get(filename, {}).get("count", 0))


def cmd_set(json_path: Path, filename: str, count: int) -> None:
    data = _load(json_path)
    data[filename] = {
        "count": count,
        "last_failure": datetime.now().isoformat(timespec="seconds"),
    }
    _save(json_path, data)


def cmd_clear(json_path: Path, filename: str) -> None:
    data = _load(json_path)
    data.pop(filename, None)
    _save(json_path, data)


def main() -> None:
    if len(sys.argv) < 4:
        print(
            f"Usage: {sys.argv[0]} get|set|clear <json_path> <filename> [count]",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    json_path = Path(sys.argv[2])
    filename = sys.argv[3]

    if command == "get":
        cmd_get(json_path, filename)
    elif command == "set":
        if len(sys.argv) < 5:
            print("set requires a count argument", file=sys.stderr)
            sys.exit(1)
        cmd_set(json_path, filename, int(sys.argv[4]))
    elif command == "clear":
        cmd_clear(json_path, filename)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
