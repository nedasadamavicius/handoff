from __future__ import annotations

import subprocess

from handoff.config import AppConfig
from handoff.workspace import Workspace, preview_file


def build_handoff_prompt(workspace: Workspace, files_opened: list[str], tools_launched: list[str]) -> str:
    workspace_text = preview_file(workspace.workspace_file, limit=3000) if workspace.workspace_file.exists() else ""
    next_text = preview_file(workspace.next_file, limit=2000) if workspace.next_file.exists() else ""
    last = workspace.last_handoff()
    last_text = last.body[:3000] if last else ""
    return f"""Draft updated workspace handoff files from the available local evidence.

Workspace: {workspace.name}

Files opened:
{chr(10).join(f"- {item}" for item in files_opened) or "- None tracked"}

Tools launched:
{chr(10).join(f"- {item}" for item in tools_launched) or "- None tracked"}

WORKSPACE.md:
{workspace_text}

LAST.md:
{last_text}

Existing NEXT.md:
{next_text}

Return exactly this structure:
## LAST.md

Markdown summary of what was done last time. Include decisions and important context.

## NEXT.md

Markdown list of the next concrete work items. Include unresolved/open items only.
"""


def draft_handoff(config: AppConfig, workspace: Workspace, files_opened: list[str], tools_launched: list[str]) -> str | None:
    if not config.ai_command:
        return None
    prompt = build_handoff_prompt(workspace, files_opened, tools_launched)
    result = subprocess.run(
        config.ai_command,
        input=prompt,
        text=True,
        capture_output=True,
        shell=True,
        cwd=str(workspace.path),
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
