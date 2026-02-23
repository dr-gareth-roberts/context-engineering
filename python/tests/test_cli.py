import subprocess
import sys
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "..", "fixtures")


def test_cli_budget():
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget", "-t", "hello world"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    output = result.stdout.strip()
    # When piped, output should be parseable as a number
    assert output.isdigit() or output.startswith("{")


def test_cli_budget_missing_args():
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_cli_pack_stdin():
    items_json = json.dumps([
        {"id": "a", "content": "hello world", "tokens": 10},
        {"id": "b", "content": "foo bar", "tokens": 20},
    ])
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "pack", "-i", "-", "-b", "50"],
        capture_output=True, text=True, input=items_json,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "selected" in data


def test_cli_no_color_env():
    """When NO_COLOR is set, output should have no ANSI escape codes."""
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget", "-t", "hello"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert "\033[" not in result.stdout
