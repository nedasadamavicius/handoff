"""Footer that fits the terminal: compact spacing first, then wraps onto more rows."""

from __future__ import annotations

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup
from textual.widgets import Footer
from textual.widgets._footer import FooterKey


def _key_width(key_display: str, description: str, compact: bool) -> int:
    # Mirrors FooterKey padding: full is " key desc ", compact is "key desc" plus a 1-cell margin.
    return cell_len(key_display) + cell_len(description) + (2 if compact else 3)


def pack_rows(widths: list[int], available: int) -> list[int]:
    """Greedy row packing; returns how many keys go on each row."""
    rows: list[int] = []
    used = 0
    for width in widths:
        if rows and used + width <= available:
            rows[-1] += 1
            used += width
        else:
            rows.append(1)
            used = width
    return rows or [0]


class ResponsiveFooter(Footer):
    DEFAULT_CSS = """
    ResponsiveFooter {
        layout: vertical;
        height: auto;
        max-height: 6;
        HorizontalGroup.footer-row {
            width: 1fr;
            height: 1;
        }
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._layout: tuple[bool, tuple[int, ...]] | None = None

    def _shown_bindings(self) -> list[tuple[Binding, bool, str]]:
        seen: set[str] = set()
        bindings = []
        for _, binding, enabled, tooltip in self.screen.active_bindings.values():
            if binding.show and binding.action not in seen:
                seen.add(binding.action)
                bindings.append((binding, enabled, tooltip))
        return bindings

    def _palette(self) -> tuple[Binding, bool, str] | None:
        if not (self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE):
            return None
        try:
            _, binding, enabled, tooltip = self.screen.active_bindings[self.app.COMMAND_PALETTE_BINDING]
        except KeyError:
            return None
        return binding, enabled, tooltip

    def _plan(self, width: int) -> tuple[bool, tuple[int, ...]]:
        """Choose compact mode and row split for the given terminal width."""
        bindings = self._shown_bindings()
        labels = [(self.app.get_key_display(binding), binding.description) for binding, _, _ in bindings]
        palette = self._palette()
        reserve = 0
        if palette is not None:
            reserve = _key_width(self.app.get_key_display(palette[0]), palette[0].description, False) + 2
        available = max(1, width - reserve)
        full = [_key_width(key, desc, False) for key, desc in labels]
        if sum(full) <= available:
            return False, (len(full),)
        compact = [_key_width(key, desc, True) for key, desc in labels]
        return True, tuple(pack_rows(compact, available))

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        compact, rows = self._plan(self.app.size.width)
        self._layout = (compact, rows)
        self.compact = compact
        bindings = iter(self._shown_bindings())
        for count in rows:
            with HorizontalGroup(classes="footer-row"):
                for _ in range(count):
                    binding, enabled, tooltip = next(bindings)
                    yield FooterKey(
                        binding.key,
                        self.app.get_key_display(binding),
                        binding.description,
                        binding.action,
                        disabled=not enabled,
                        tooltip=tooltip,
                    ).data_bind(compact=Footer.compact)
        palette = self._palette()
        if palette is not None:
            binding, enabled, _ = palette
            yield FooterKey(
                binding.key,
                self.app.get_key_display(binding),
                binding.description,
                binding.action,
                classes="-command-palette",
                disabled=not enabled,
                tooltip=binding.tooltip or binding.description,
            )

    def on_resize(self, event: events.Resize) -> None:
        if self._bindings_ready and self._plan(self.app.size.width) != self._layout:
            self.call_after_refresh(self.recompose)
