from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

ConfigRoot = Annotated[Path, typer.Option("--root", hidden=True, help="User config root.")]
RepositoryDirectory = Annotated[Path, typer.Argument(help="Repository directory.")]
