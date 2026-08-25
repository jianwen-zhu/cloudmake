from __future__ import annotations

import argparse
import base64


def main() -> int:
    parser = argparse.ArgumentParser(description="Encode one cloudmake control value")
    parser.add_argument("value")
    arguments = parser.parse_args()
    print(base64.urlsafe_b64encode(arguments.value.encode("utf-8")).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
