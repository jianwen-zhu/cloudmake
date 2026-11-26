"""Check Colab access through the public CLI without forwarding its output."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time


PROBE_TIMEOUT = 10
RETRY_DELAYS = (1, 2)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Rich can wrap the CLI's exception message before the URL.
REQUEST_FAILURE = r"failed to issue request\s+get\s+\S+:\s*"


def classify(returncode: int, output: str) -> str:
    message = ANSI_ESCAPE.sub("", output).lower()
    if re.search(
        r"\binvalid_grant\b|\bhttp\s+401\b|\b401\s+client error\b"
        rf"|{REQUEST_FAILURE}unauthorized\b",
        message,
    ):
        return "authentication-required"
    if re.search(
        r"\bhttp\s+403\b|\b403\s+client error\b|\bscope_not_permitted\b"
        rf"|{REQUEST_FAILURE}forbidden\b",
        message,
    ):
        return "access-denied"
    if re.search(
        r"\b(?:ssleoferror|unexpected_eof_while_reading|readtimeout|"
        r"connecttimeout|connectionerror|connection reset by peer|"
        r"temporary failure in name resolution)\b"
        r"|\bhttp\s+(?:408|429|50[0234])\b"
        r"|\b(?:408|429|50[0234])\s+(?:client|server) error\b"
        rf"|{REQUEST_FAILURE}(?:request timeout|too many requests|"
        r"internal server error|bad gateway|service unavailable|gateway timeout)\b",
        message,
    ):
        return "transient"
    # Refresh failure and missing credentials can produce the same prompt.
    # Some CLI versions also report an empty listing with exit zero after an
    # ADC failure, so inspect these messages before accepting exit status.
    if any(
        marker in message
        for marker in (
            "to authorize colab-cli",
            "enter the authorization code",
            "no valid default credentials found",
        )
    ):
        return "authorization-unconfirmed"
    return "ready" if returncode == 0 else "unclassified"


def probe(client: str) -> str:
    try:
        result = subprocess.run(
            [client, "sessions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=PROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "transient"
    except OSError:
        return "client-unavailable"
    # A successful listing can contain user-chosen session names on stdout.
    # The CLI prints the OAuth prompt heading and ADC diagnostic to stderr.
    output = result.stderr if result.returncode == 0 else result.stderr + result.stdout
    return classify(result.returncode, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True)
    args = parser.parse_args()

    outcome = probe(args.client)
    for delay in RETRY_DELAYS:
        if outcome not in {"transient", "authorization-unconfirmed"}:
            break
        print(
            f"[doctor] Colab access check could not complete. Retrying in {delay}s.",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)
        outcome = probe(args.client)
    if outcome == "ready":
        return 0

    explanation = {
        "transient": (
            "Colab is temporarily unavailable. Check your network and try "
            "'cloudmake -b colab --doctor' again shortly."
        ),
        "authorization-unconfirmed": (
            "Colab authorization could not be verified. The CLI offered sign-in, "
            "which can also follow a failed credential refresh. Try "
            "'cloudmake -b colab --doctor' again shortly. If the prompt persists, "
            "run 'colab sessions' in your own terminal to check sign-in."
        ),
        "authentication-required": (
            "Colab authentication is required. Run 'colab sessions' in your own "
            "terminal to restore sign-in, then rerun 'cloudmake -b colab --doctor'."
        ),
        "access-denied": (
            "Colab denied access. Check the selected Google account's Colab "
            "permissions or scopes with the official CLI."
        ),
        "client-unavailable": "Cloudmake could not launch the configured Colab CLI.",
        "unclassified": (
            "Colab access could not be verified. Run 'colab sessions' in your "
            "own terminal for the provider's diagnostic."
        ),
    }
    print(f"[doctor] {explanation[outcome]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
