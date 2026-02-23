import subprocess
import sys


def test_cli_budget():
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget", "--text", "hello"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().isdigit()
