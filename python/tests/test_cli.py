import subprocess
import sys
import json
import os
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "..", "fixtures")
MONOREPO_ROOT = os.path.join(PROJECT_ROOT, "..")


def run_cli(*args, input=None, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", *args],
        capture_output=True, text=True, input=input,
        cwd=cwd or MONOREPO_ROOT,
    )


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------


def test_cli_budget():
    result = run_cli("budget", "-t", "hello world")
    assert result.returncode == 0
    output = result.stdout.strip()
    # When piped, output should be parseable as a number
    assert output.isdigit() or output.startswith("{")


def test_cli_budget_missing_args():
    result = run_cli("budget")
    assert result.returncode != 0


def test_cli_pack_stdin():
    items_json = json.dumps([
        {"id": "a", "content": "hello world", "tokens": 10},
        {"id": "b", "content": "foo bar", "tokens": 20},
    ])
    result = run_cli("pack", "-i", "-", "-b", "50", input=items_json)
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
        cwd=MONOREPO_ROOT,
    )
    assert result.returncode == 0
    assert "\033[" not in result.stdout


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------

ITEMS_JSON = json.dumps([
    {"id": "a", "content": "hello world", "tokens": 10, "kind": "system", "priority": 10},
    {"id": "b", "content": "foo bar", "tokens": 20, "kind": "retrieval", "priority": 5},
])


def test_cli_trace_stdin():
    """trace command with JSON items on stdin."""
    result = run_cli("trace", "-i", "-", "-b", "50", input=ITEMS_JSON)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "steps" in data


def test_cli_lint_valid():
    """lint -s context-item -i items.json validates OK."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    result = run_cli("lint", "-s", "context-item", "-i", items_path)
    assert result.returncode == 0, result.stderr
    assert "Valid" in result.stdout or "valid" in result.stdout.lower()


def test_cli_lint_invalid():
    """lint with invalid data returns non-zero."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        json.dump({"not_valid": True}, tmp)
        tmp_path = tmp.name
    try:
        result = run_cli("lint", "-s", "context-item", "-i", tmp_path)
        assert result.returncode != 0
    finally:
        os.unlink(tmp_path)


def test_cli_place_stdin():
    """place command with items from a temp file (pipe to avoid tty)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp.write(ITEMS_JSON)
        tmp_path = tmp.name
    try:
        result = run_cli("place", "-i", tmp_path)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2
    finally:
        os.unlink(tmp_path)


def test_cli_quality():
    """quality command with items file."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    result = run_cli("quality", "-i", items_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "itemCount" in data
    assert "overall" in data
    assert data["itemCount"] > 0


def test_cli_effective_budget():
    """effective-budget -t 8000."""
    result = run_cli("effective-budget", "-t", "8000")
    assert result.returncode == 0, result.stderr
    budget = int(result.stdout.strip())
    assert 0 < budget <= 8000


def test_cli_effective_budget_with_model():
    """effective-budget -t 8000 -m claude."""
    result = run_cli("effective-budget", "-t", "8000", "-m", "claude")
    assert result.returncode == 0, result.stderr
    budget = int(result.stdout.strip())
    assert 0 < budget <= 8000


def test_cli_handoff():
    """handoff command with items and budget, verify JSON output."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    result = run_cli("handoff", "-i", items_path, "-b", "100")
    assert result.returncode == 0, result.stderr
    # Output is JSONL -- each line should be valid JSON
    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    assert len(lines) > 0
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


def test_cli_pickup_stdin():
    """Create handoff, then pipe JSONL to pickup."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    handoff_result = run_cli("handoff", "-i", items_path, "-b", "100")
    assert handoff_result.returncode == 0, handoff_result.stderr

    jsonl = handoff_result.stdout
    pickup_result = run_cli("pickup", "-i", "-", input=jsonl)
    assert pickup_result.returncode == 0, pickup_result.stderr
    data = json.loads(pickup_result.stdout)
    assert "items" in data
    assert "stats" in data


def test_cli_cost():
    """cost command with items, budget, model."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    result = run_cli(
        "cost", "-i", items_path, "-b", "200",
        "-m", "claude-sonnet-4-6",
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "model" in data
    assert "inputTokens" in data
    assert "costWithCache" in data
    assert "savings" in data


def test_cli_lint_new_schemas():
    """lint validates beads-issue, cost-estimate, pipeline-result, cache-aware-pack schemas."""
    schema_data = {
        "beads-issue": {
            "id": "bd-1",
            "title": "Test",
            "status": "open",
            "priority": 2,
            "issue_type": "task",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "cost-estimate": {
            "model": "claude-sonnet-4-6",
            "inputTokens": 1000,
            "cachedTokens": 500,
            "uncachedTokens": 500,
            "outputTokens": 100,
            "costWithoutCache": 0.01,
            "costWithCache": 0.005,
            "savings": 0.005,
            "savingsPercent": 50,
            "cacheEfficiency": 0.5,
        },
        "pipeline-result": {
            "selected": [],
            "dropped": [],
            "totalTokens": 0,
            "budget": {"maxTokens": 4096},
            "inputCount": 0,
            "stages": ["pack"],
        },
        "cache-aware-pack": {
            "selected": [],
            "dropped": [],
            "totalTokens": 0,
            "budget": {"maxTokens": 4096},
            "stats": {},
            "cacheKey": "abc",
            "cacheableTokens": 100,
            "volatileTokens": 50,
            "cacheEfficiency": 0.67,
            "partitionBoundaries": [0, 2],
        },
    }
    for schema_name, data in schema_data.items():
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(data, tmp)
            tmp_path = tmp.name
        try:
            result = run_cli("lint", "-s", schema_name, "-i", tmp_path)
            assert result.returncode == 0, (
                f"Schema {schema_name} validation failed: {result.stderr}"
            )
        finally:
            os.unlink(tmp_path)


def test_cli_pack_file():
    """pack with -i items file (not stdin)."""
    items_path = os.path.join(FIXTURES_DIR, "context-items.json")
    result = run_cli("pack", "-i", items_path, "-b", "100")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "selected" in data
    assert "dropped" in data


def test_cli_invalid_command():
    """Verify unknown command fails."""
    result = run_cli("nonexistent-command")
    assert result.returncode != 0


def test_cli_error_file_not_found():
    """CLI produces clean error message for missing file, not a raw traceback."""
    result = run_cli("pack", "-i", "/nonexistent/path/items.json")
    assert result.returncode == 1
    assert "File not found" in result.stderr or "No such file" in result.stderr
    # Should NOT have a Python traceback
    assert "Traceback" not in result.stderr


def test_cli_error_invalid_json():
    """CLI produces clean error for invalid JSON input."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp.write("{broken json")
        tmp_path = tmp.name
    try:
        result = run_cli("pack", "-i", tmp_path)
        assert result.returncode == 1
        assert "JSON" in result.stderr or "json" in result.stderr
        assert "Traceback" not in result.stderr
    finally:
        os.unlink(tmp_path)


def test_cli_diff():
    """diff command with --before and --after pack files."""
    # Create two temporary pack files with different items
    before = {
        "selected": [
            {"id": "a", "content": "hello", "tokens": 10},
            {"id": "b", "content": "world", "tokens": 10},
        ],
        "dropped": [],
        "totalTokens": 20,
        "budget": {"maxTokens": 100},
    }
    after = {
        "selected": [
            {"id": "a", "content": "hello", "tokens": 10},
            {"id": "c", "content": "new item", "tokens": 15},
        ],
        "dropped": [],
        "totalTokens": 25,
        "budget": {"maxTokens": 100},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as bf:
        json.dump(before, bf)
        before_path = bf.name
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as af:
        json.dump(after, af)
        after_path = af.name
    try:
        result = run_cli("diff", "--before", before_path, "--after", after_path)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert "added" in data
        assert "removed" in data
        assert "changed" in data
        assert "kept" in data
    finally:
        os.unlink(before_path)
        os.unlink(after_path)
