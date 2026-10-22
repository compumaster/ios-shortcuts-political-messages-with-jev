"""Sign generated shortcuts on a Mac; never upload to a third-party signer."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"),
                        help="directory containing *.unsigned.shortcut (default: dist)")
    args = parser.parse_args()
    if sys.platform != "darwin" or not shutil.which("shortcuts"):
        parser.exit(1, "Signing requires a Mac with Apple's shortcuts command. No upload or signed output was attempted.\n")
    sources = sorted(args.directory.glob("*.unsigned.shortcut"))
    if not sources:
        parser.exit(1, "No unsigned shortcuts found in the selected directory.\n")
    try:
        for source in sources:
            workflow = plistlib.loads(source.read_bytes())
            if not isinstance(workflow, dict) or not workflow.get("WFWorkflowActions"):
                raise ValueError(f"Not a shortcut: {source}")
            for action in workflow["WFWorkflowActions"]:
                parameters = action.get("WFWorkflowActionParameters", {})
                if parameters.get("CustomOutputName") == "OpenRouter API key" and parameters.get("WFTextActionText") != "":
                    raise ValueError("Sign the blank-key build. Enter your OpenRouter key only after import.")
            output = source.with_name(source.name.removesuffix(".unsigned.shortcut") + ".shortcut")
            with tempfile.TemporaryDirectory(prefix=".sign-", dir=args.directory) as temporary:
                signed = Path(temporary) / "signed.shortcut"
                subprocess.run(
                    ["shortcuts", "sign", "--mode", "anyone", "--input", str(source), "--output", str(signed)],
                    check=True, timeout=120,
                )
                # Container validation is not a substitute for an iPhone import test.
                with signed.open("rb") as stream:
                    if stream.read(4) != b"AEA1" or signed.stat().st_size <= 4:
                        raise ValueError(f"Signing did not return an AEA1 shortcut for {source}")
                os.replace(signed, output)
            print(f"Signed: {output}")
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Signing failed: {exc}\nUnsigned sources were preserved. No remote fallback was attempted.\n")


if __name__ == "__main__":
    main()
