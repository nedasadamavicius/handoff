# Themes

`handoff` ships with the `graphite-crimson` theme by default. Custom themes are global user preferences stored in `~/.handoff/themes/`.

```yaml
# ~/.handoff/themes/my-theme.yaml
name: my-theme
dark: true
primary: "#DC143C"
secondary: "#8B0000"
accent: "#C0392B"
warning: "#DC143C"
success: "#8B0000"
error: "#FF3333"
background: "#0d0d0d"
surface: "#171717"
panel: "#222222"
foreground: "#e8e8e8"
```

A copy of `graphite-crimson.yaml` is written to `~/.handoff/themes/` on first run as a starting point to copy and edit.

Color roles:
| Key | Used for |
|---|---|
| `primary` | Focus ring on the file pane, app title |
| `accent` | Focus ring on the preview pane |
| `success` | Last Session panel border and header |
| `warning` | What's Next panel border and header |
| `background` | App background |
| `surface` | Widget backgrounds |
| `panel` | Panel backgrounds, unfocused borders |
| `foreground` | Primary text |
| `secondary` / `error` | Secondary elements, error notifications |
