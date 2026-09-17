"""Pull the three adva mainlines and check what this study depends on.

`adva` advanced three times in an hour on 2026-09-17 (#189, #190, #191), and
each pull had to answer the same two questions by hand: what moved, and did
anything this study conforms to move with it. The second question is the one
that matters -- the registry in `docs/claims.toml` was built to a field set and
a tool (`scripts/navigate.py`), and both were read once and then trusted.

Two disciplines are structural rather than stylistic:

- **RECORDED and OBSERVED HERE are labelled separately**, as in Adva's own
  `navigate.py`: a commit id read back from git is an observation made now; a
  version recorded in the state file is what was true last time.
- **A clone that cannot be written is not updated, and that is said** rather
  than reported as up to date. `~/Adva/adva-machine` lives outside this
  workspace, so its remote head is observed through the API and compared with
  its working copy; nothing is fetched into it.

Usage: python3 scripts/adva_pull.py [--no-fetch]
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/adva-state.json"

# What this study conforms to. If any of these moves, the conformance claim in
# `docs/conformance.contract.json` has to be re-checked rather than assumed.
DEPENDENCIES = (
    "scripts/navigate.py",
    "scripts/problem_card.py",
    "scripts/run_bounded.py",
    "docs/claims.toml",
)

REPOS = {
    "adva": {"clone": Path("/tmp/adva-main"), "api": "mountain/adva"},
    "adva-library": {"clone": Path("/tmp/adva-lib"), "api": "mountain/adva-library"},
    "adva-machine": {"clone": Path.home() / "Adva/adva-machine", "api": "mountain/adva-machine"},
}


def git(clone: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def api_head(name: str) -> tuple[str, str]:
    url = f"https://api.github.com/repos/{name}/commits?per_page=1"
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.load(response)
        first = payload[0]
        return first["sha"], first["commit"]["author"]["date"][:16]
    except Exception as exc:  # noqa: BLE001 - report and continue
        return "", f"API error: {type(exc).__name__}"


def claims_field_set(clone: Path, rev: str = "HEAD") -> list[str]:
    import tomllib

    raw = subprocess.run(["git", "-C", str(clone), "show", f"{rev}:docs/claims.toml"],
                         capture_output=True).stdout
    if not raw:
        return []
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".toml", delete=False)
    handle.write(raw)
    handle.close()
    parsed = tomllib.load(open(handle.name, "rb"))
    return sorted(parsed["claim"][0].keys())


def main() -> int:
    do_fetch = "--no-fetch" not in sys.argv
    previous = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    state: dict = {}

    print("每个提交号都是 OBSERVED HERE；与上次记录的对比是 RECORDED。\n")
    for name, spec in REPOS.items():
        clone: Path = spec["clone"]
        print(f"═══ {name}")

        if not clone.exists():
            head, when = api_head(spec["api"])
            print(f"  OBSERVED HERE  无本地克隆；远端 {head[:8]} {when}")
            state[name] = {"remote": head, "local": None}
            print()
            continue

        local_before = git(clone, "rev-parse", "HEAD")
        writable = True
        if do_fetch:
            fetched = subprocess.run(
                ["git", "-C", str(clone), "-c", "http.version=HTTP/1.1",
                 "fetch", "--depth=200", "origin", "main"],
                capture_output=True, text=True)
            if fetched.returncode != 0:
                writable = False
                print(f"  OBSERVED HERE  无法 fetch（工作区外或网络）："
                      f"{fetched.stderr.strip().splitlines()[-1][:70] if fetched.stderr.strip() else '?'}")

        merged = ""
        if writable:
            remote = git(clone, "rev-parse", "origin/main")
            if local_before and remote and local_before != remote:
                result = subprocess.run(["git", "-C", str(clone), "merge", "--ff-only", remote],
                                        capture_output=True, text=True)
                merged = result.stdout.strip().splitlines()[-1][:60] if result.returncode == 0 else \
                         f"merge --ff-only refused: {result.stderr.strip().splitlines()[-1][:50]}"
            elif local_before == remote:
                merged = "already at the remote head"

        local_after = git(clone, "rev-parse", "HEAD")
        subject = git(clone, "log", "-1", "--format=%h %ad %s", "--date=short")
        print(f"  OBSERVED HERE  local  {subject[:74]}")
        if merged:
            print(f"  OBSERVED HERE  {merged}")
        if not writable:
            remote, when = api_head(spec["api"])
            print(f"  OBSERVED HERE  remote {remote[:8]} {when}  "
                  f"({'same as local' if remote.startswith(local_after[:8]) else 'DIFFERS -- not fetched here'})")

        record = previous.get(name, {}).get("head")
        if record and record != local_after:
            print(f"  RECORDED      上一次拉到的是 {record[:8]} —— 本轮前进/变化")
        state[name] = {"remote": git(clone, "rev-parse", "origin/main") or None, "local": local_after}

        # The dependencies this study conforms to, compared across the pull.
        if local_before and local_after and local_before != local_after:
            print("  依赖检查（本次增量内是否变动）：")
            for path in DEPENDENCIES:
                changed = subprocess.run(["git", "-C", str(clone), "diff", "--quiet",
                                          f"{local_before}..{local_after}", "--", path],
                                         capture_output=True)
                mark = "⚠ 变了" if changed.returncode == 1 else "✓ 未变"
                print(f"    {mark:8} {path}")
            if "docs/claims.toml" in DEPENDENCIES:
                before = claims_field_set(clone, local_before)
                after = claims_field_set(clone, local_after)
                print(f"    {'⚠ 字段集变了' if before != after else '✓ 字段集未变'}"
                      f"  ({len(before)} 个字段)")
        print()

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OBSERVED HERE  状态写入 {STATE.relative_to(ROOT)}")
    print("                （下次运行据此说出一轮里前进了什么）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
