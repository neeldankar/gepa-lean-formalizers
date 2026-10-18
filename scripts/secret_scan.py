"""Fail if staged changes (default) or the whole git history (--history) contain a secret.

Looks for the literal values in .env and for common key formats. Prints where, never what.
Stdlib only, so the git hooks run with any python3.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "OpenAI-style key": r"sk-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}",
    "Hugging Face token": r"hf_[A-Za-z0-9]{30,}",
    "AWS key": r"AKIA[0-9A-Z]{16}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def env_values(path):
    path = Path(path)
    if not path.exists():
        return []
    values = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            value = line.split("=", 1)[1].strip().strip("'\"")
            if len(value) >= 8:
                values.append(value)
    return values


def find_secrets(text, values):
    """Return descriptions of what was found, e.g. 'line 12: value of an .env key'."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        if any(v in line for v in values):
            found.append(f"line {n}: value of an .env key")
        for name, pattern in PATTERNS.items():
            if re.search(pattern, line):
                found.append(f"line {n}: looks like a {name}")
    return found


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def main():
    history = "--history" in sys.argv
    if history:
        text = git("log", "-p", "--all", "--no-color")
        where = "git history"
    else:
        staged = git("diff", "--cached", "--name-only").split()
        if ".env" in staged:
            print("secret scan: .env is staged; unstage it")
            sys.exit(1)
        text = git("diff", "--cached", "-U0", "--no-color")
        where = "staged changes"
    found = find_secrets(text, env_values(ROOT / ".env"))
    if found:
        print(f"secret scan: possible secrets in {where} (line numbers are in `git {'log -p' if history else 'diff --cached -U0'}` output):")
        print("\n".join(found[:20]))
        sys.exit(1)
    print(f"secret scan: {where} clean")


if __name__ == "__main__":
    main()
