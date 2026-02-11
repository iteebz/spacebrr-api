from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


def list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted([p.stem for p in TEMPLATES_DIR.glob("*.md")])


def get_template(name: str) -> str:
    template_path = TEMPLATES_DIR / f"{name}.md"
    if not template_path.exists():
        raise ValueError(f"Template '{name}' not found")
    return template_path.read_text()


def template_exists(name: str) -> bool:
    return (TEMPLATES_DIR / f"{name}.md").exists()
