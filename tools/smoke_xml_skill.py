#!/usr/bin/env python3
"""Build the XML skill source kit from its ZIP and parse a minimal fixture.

Requires Node.js, pnpm and package-download access. This is a release/CI check,
not an assertion that hosted chat sandboxes can install these dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path)
    args = parser.parse_args()
    registry = json.loads((ROOT / "teams/registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["skills"] if item["name"] == "xml-team")
    archive = (
        args.archive
        or ROOT
        / "release/team-skills"
        / registry["release_version"]
        / f"xml-team-{entry['version']}.zip"
    )
    with tempfile.TemporaryDirectory(prefix="manacost-xml-skill-") as temporary:
        destination = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                if (
                    not (destination / item.filename)
                    .resolve()
                    .is_relative_to(destination)
                ):
                    raise ValueError("unsafe archive path")
            bundle.extractall(destination)
        runtime = destination / "xml-team/runtime"
        pnpm = (
            ["pnpm"]
            if os.name != "nt"
            else [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "pnpm"]
        )
        subprocess.run([*pnpm, "install", "--frozen-lockfile"], cwd=runtime, check=True)
        subprocess.run([*pnpm, "run", "build"], cwd=runtime, check=True)
        code = "const {parseReplayDocument}=await import('./dist/node.js'); const doc=parseReplayDocument('<HSReplay><Game><GameEntity id=\"1\"><Tag tag=\"202\" value=\"1\"/></GameEntity></Game></HSReplay>'); if(doc.games.length!==1 || doc.games[0].packets.length!==1) throw Error('XML packet preservation failed'); console.log('XML skill ZIP: install, build and packet parsing passed');"
        subprocess.run(
            ["node", "--input-type=module", "-e", code], cwd=runtime, check=True
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
