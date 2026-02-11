import shutil
import tomllib
from pathlib import Path

MARKER = "# managed by space launch"


def sync_bin_scripts() -> list[str]:
    bin_dir = Path.home() / "bin"
    bin_dir.mkdir(exist_ok=True)
    space_dir = Path.home() / "space"
    uv_path = shutil.which("uv") or "uv"

    current_scripts: dict[str, Path] = {}
    for pyproject in space_dir.glob("**/pyproject.toml"):
        if ".venv" in pyproject.parts or "node_modules" in pyproject.parts:
            continue
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        scripts = data.get("project", {}).get("scripts", {})
        for name in scripts:
            current_scripts[name] = pyproject.parent

    for script in bin_dir.iterdir():
        if script.is_file() and MARKER in script.read_text() and script.name not in current_scripts:
            script.unlink()

    created = []
    for name, repo_dir in current_scripts.items():
        script = bin_dir / name
        expected = f"""#!/bin/sh
{MARKER}
SPACE_INVOCATION_DIR="${{SPACE_INVOCATION_DIR:-$(pwd)}}"
export SPACE_INVOCATION_DIR
cd {repo_dir} || exit 1
exec {uv_path} run "$(basename "$0")" "$@"
"""
        if not script.exists() or script.read_text() != expected:
            script.write_text(expected)
            script.chmod(0o755)
            created.append(name)

    return created
