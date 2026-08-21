"""THE SPIKE. Run this on the VM before building anything else on top.

Claude Desktop is an Electron app, so it should expose a Chromium accessibility
tree through Windows UI Automation — which is the difference between driving it
by named controls and driving it by clicking at coordinates. This script proves
whether that is true, and if so hands you the selectors to put in config.

    python -m jarvis_work.agent.spike_uia            # dump + verdict
    python -m jarvis_work.agent.spike_uia --depth 12 # go deeper
    python -m jarvis_work.agent.spike_uia --write "hello from jarvis"

The --write form is the real test: it attempts to place text in the composer
WITHOUT the window having focus. If that works, Jarvis can drive Claude on the
VM while you keep using the VM for other things. If it only works with focus,
the VM becomes single-purpose — still fine, but worth knowing now.

Chromium builds its accessibility tree lazily. If the tree comes back nearly
empty, launch Claude once with --force-renderer-accessibility and re-run.
"""
from __future__ import annotations

import argparse
import sys

CANDIDATE_TYPES = {"EditControl", "DocumentControl", "TextControl", "GroupControl", "PaneControl"}


def _require_uia():
    try:
        import uiautomation as auto
        return auto
    except ImportError:
        sys.exit("uiautomation is not installed. Run: pip install uiautomation psutil\n"
                 "(Windows only — this spike cannot run on macOS or Linux.)")


def _proc_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return "?"


def _patterns(auto, ctrl) -> list[str]:
    """Which UIA patterns this control actually supports — the useful signal."""
    found = []
    for name, pid in (("Value", auto.PatternId.ValuePattern),
                      ("Text", auto.PatternId.TextPattern),
                      ("Invoke", auto.PatternId.InvokePattern),
                      ("LegacyIAccessible", auto.PatternId.LegacyIAccessiblePattern),
                      ("Scroll", auto.PatternId.ScrollPattern)):
        try:
            if ctrl.GetPattern(pid):
                found.append(name)
        except Exception:
            pass
    return found


def find_claude_windows(auto) -> list:
    """Top-level windows belonging to a Claude.exe process."""
    out = []
    root = auto.GetRootControl()
    for w in root.GetChildren():
        try:
            pid = w.ProcessId
        except Exception:
            continue
        if "claude" in _proc_name(pid).lower():
            out.append(w)
    return out


def walk(auto, ctrl, depth: int, max_depth: int, cap: list, candidates: list, indent: int = 0):
    if depth > max_depth or cap[0] <= 0:
        return
    cap[0] -= 1
    try:
        ctype = ctrl.ControlTypeName
        name = (ctrl.Name or "")[:70].replace("\n", " ")
        aid = ctrl.AutomationId or ""
        cls = ctrl.ClassName or ""
    except Exception:
        return

    pats = _patterns(auto, ctrl)
    print(f"{'  ' * indent}{ctype}  name={name!r}  id={aid!r}  class={cls!r}  patterns={','.join(pats) or '-'}")

    if ctype in CANDIDATE_TYPES and ("Value" in pats or "Text" in pats):
        candidates.append({"type": ctype, "name": name, "automation_id": aid,
                           "class": cls, "patterns": pats, "depth": depth,
                           "control": ctrl})

    try:
        for child in ctrl.GetChildren():
            walk(auto, child, depth + 1, max_depth, cap, candidates, indent + 1)
    except Exception:
        pass


def try_write(auto, candidates: list, text: str) -> None:
    print("\n=== WRITE TEST (no focus) ===")
    if not candidates:
        print("No writable candidates found — nothing to try.")
        return
    for c in candidates:
        if "Value" not in c["patterns"]:
            continue
        label = f"{c['type']} id={c['automation_id']!r} name={c['name']!r}"
        try:
            vp = c["control"].GetPattern(auto.PatternId.ValuePattern)
            vp.SetValue(text)
            after = ""
            try:
                after = c["control"].GetPattern(auto.PatternId.ValuePattern).Value
            except Exception:
                pass
            ok = text in (after or "")
            print(f"  {'OK  ' if ok else 'MEH '} {label} -> readback={after[:60]!r}")
            if ok:
                print("\n  >>> This is your composer. Put these in config.yaml:")
                print(f"      composer_automation_id: {c['automation_id']!r}")
                print(f"      composer_control_type:  {c['type']!r}")
                print(f"      composer_name:          {c['name']!r}")
                return
        except Exception as e:
            print(f"  FAIL {label} -> {e}")
    print("\n  No control accepted SetValue without focus.")
    print("  Fall back to: focus the window, then send keystrokes (see claude_driver.py).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect Claude Desktop's UI Automation tree")
    ap.add_argument("--depth", type=int, default=10, help="max tree depth to walk")
    ap.add_argument("--max-nodes", type=int, default=1200, help="node budget, stops runaway walks")
    ap.add_argument("--write", metavar="TEXT", default="", help="attempt an unfocused write of TEXT")
    args = ap.parse_args()

    auto = _require_uia()
    wins = find_claude_windows(auto)
    if not wins:
        sys.exit("No Claude Desktop window found. Start Claude and try again.\n"
                 "If it IS running, its process may not be named Claude.exe — check Task Manager.")

    print(f"Found {len(wins)} Claude window(s).\n")
    all_candidates: list = []
    for w in wins:
        print(f"=== WINDOW: {w.Name!r} class={w.ClassName!r} pid={w.ProcessId} ===")
        cap = [args.max_nodes]
        walk(auto, w, 0, args.depth, cap, all_candidates)
        if cap[0] <= 0:
            print(f"  ...node budget ({args.max_nodes}) exhausted — rerun with --max-nodes higher")
        print()

    print(f"=== {len(all_candidates)} writable/readable candidate control(s) ===")
    for c in all_candidates[:25]:
        print(f"  depth={c['depth']:<3} {c['type']:<16} id={c['automation_id']!r:<24} "
              f"name={c['name']!r:<40} patterns={','.join(c['patterns'])}")

    if args.write:
        try_write(auto, all_candidates, args.write)

    print("\n=== VERDICT ===")
    if not all_candidates:
        print("Tree looks EMPTY. Try relaunching Claude with --force-renderer-accessibility.")
        print("If it is still empty, UIA is not viable and the fallback is coordinate clicking.")
    elif len(all_candidates) < 3:
        print("Tree is THIN. Workable, but expect fragile selectors. Try a deeper --depth first.")
    else:
        print("Tree is RICH. UIA driving is viable — proceed with the agent bridge.")


if __name__ == "__main__":
    main()
