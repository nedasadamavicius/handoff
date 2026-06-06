from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from textual.theme import Theme

if TYPE_CHECKING:
    from textual.app import App
    from handoff.config import AppConfig


GRAPHITE_CRIMSON = Theme(
    name="graphite-crimson",
    dark=True,
    primary="#DC143C",
    secondary="#8B0000",
    accent="#C0392B",
    warning="#DC143C",
    success="#8B0000",
    error="#FF3333",
    background="#0d0d0d",
    surface="#171717",
    panel="#222222",
    foreground="#e8e8e8",
)

BUNDLED_THEMES: list[Theme] = [GRAPHITE_CRIMSON]

_THEME_STR_FIELDS = {
    "primary", "secondary", "accent", "warning", "success", "error",
    "background", "surface", "panel", "foreground",
}


def _theme_to_yaml(theme: Theme) -> str:
    data: dict = {"name": theme.name, "dark": theme.dark}
    for f in _THEME_STR_FIELDS:
        value = getattr(theme, f, None)
        if value is not None:
            data[f] = value
    return yaml.safe_dump(data, sort_keys=False)


def load_theme_file(path: Path) -> Theme | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    name = raw.get("name")
    if not name:
        return None
    kwargs: dict = {"name": name, "dark": bool(raw.get("dark", True))}
    for f in _THEME_STR_FIELDS:
        if raw.get(f):
            kwargs[f] = raw[f]
    try:
        return Theme(**kwargs)
    except Exception:
        return None


def ensure_themes_dir(themes_dir: Path) -> None:
    themes_dir.mkdir(parents=True, exist_ok=True)
    default_path = themes_dir / "graphite-crimson.yaml"
    if not default_path.exists():
        default_path.write_text(_theme_to_yaml(GRAPHITE_CRIMSON), encoding="utf-8")


def load_user_themes(themes_dir: Path) -> list[Theme]:
    if not themes_dir.is_dir():
        return []
    themes = []
    for path in sorted(themes_dir.glob("*.yaml")):
        theme = load_theme_file(path)
        if theme is not None:
            themes.append(theme)
    return themes


def register_all_themes(app: App, config: AppConfig) -> None:
    for theme in BUNDLED_THEMES:
        app.register_theme(theme)
    for theme in load_user_themes(config.themes_dir):
        app.register_theme(theme)
    try:
        app.theme = config.theme
    except Exception:
        app.theme = GRAPHITE_CRIMSON.name
