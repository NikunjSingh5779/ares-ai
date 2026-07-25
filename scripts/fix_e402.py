"""Fix E402: move all imports after `logger = logging.getLogger(__name__)` above it.

Safe: only moves import lines, preserves all other code in original order,
and verifies the file still compiles (syntax check) after each edit.
"""

import ast
import sys
from pathlib import Path

FILES = [
    "agents/execution.py",
    "agents/market_analyst.py",
    "agents/memory.py",
    "agents/quant.py",
    "agents/retry.py",
    "agents/risk.py",
    "agents/router.py",
    "agents/vision.py",
]


def has_syntax_error(content: str) -> bool:
    try:
        ast.parse(content)
        return False
    except SyntaxError:
        return True


def fix_file(filepath: str) -> tuple[bool, str]:
    path = Path(filepath)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    logger_idx = None
    logger_line = "logger = logging.getLogger(__name__)"
    for i, line in enumerate(lines):
        if logger_line in line:
            logger_idx = i
            break

    if logger_idx is None:
        return False, "logger line not found"

    # Collect everything AFTER the logger line
    after = lines[logger_idx + 1 :]

    # Split after-logger content into: [import_block, non_import_rest]
    import_block = []
    non_import_rest = []
    in_imports = False
    found_first_import = False

    for line in after:
        stripped = line.strip()
        is_import = stripped.startswith("import ") or stripped.startswith("from ")
        is_empty = stripped == ""

        if is_import:
            import_block.append(line)
            in_imports = True
            found_first_import = True
        elif is_empty and found_first_import:
            # blank line between imports — keep it as part of import block
            # but only if we've already started seeing imports
            import_block.append(line)
        else:
            if found_first_import and in_imports:
                # We were in imports section and hit a non-import, non-blank line
                in_imports = False
            non_import_rest.append(line)

    if not import_block:
        return False, "no imports after logger line to move"

    # Reconstruct:
    # [content before logger line including `import logging`]
    # + [blank line]
    # + [moved imports]
    # + [blank line]
    # + [logger line]
    # + [rest after logger, minus the moved imports]

    prefix = lines[:logger_idx]

    # Ensure prefix ends cleanly
    while prefix and prefix[-1].strip() == "":
        prefix = prefix[:-1]

    # Build result
    result_lines = []
    result_lines.extend(prefix)
    result_lines.append("\n")

    # Add the import block (trim trailing blank lines)
    while import_block and import_block[-1].strip() == "":
        import_block = import_block[:-1]
    result_lines.extend(import_block)

    result_lines.append("\n")
    result_lines.append(lines[logger_idx])

    # Add rest (non-import content after logger)
    # Trim leading blank lines from rest
    while non_import_rest and non_import_rest[0].strip() == "":
        non_import_rest = non_import_rest[1:]

    if non_import_rest:
        result_lines.append("\n")
        result_lines.extend(non_import_rest)

    result = "".join(result_lines)

    # Validate syntax
    if has_syntax_error(result):
        return False, "introduced syntax error"

    if result == original:
        return False, "no change needed"

    path.write_text(result, encoding="utf-8")
    return True, f"fixed ({len(import_block)} import line(s) moved)"


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    errors = 0
    for rel_path in FILES:
        full_path = repo_root / rel_path
        if not full_path.exists():
            print(f"  SKIP  {rel_path} — not found")
            continue
        ok, msg = fix_file(str(full_path))
        if ok:
            print(f"  OK    {rel_path} — {msg}")
        else:
            print(f"  FAIL  {rel_path} — {msg}")
            errors += 1

    if errors:
        print(f"\n{errors} file(s) failed")
        sys.exit(1)
    else:
        print("\nAll files processed successfully")
