"""Read-only documentation contract checks; standard library and local Git only."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

REGISTER = "docs/document-register.json"
KINDS = {"authority", "entry", "reference", "decision", "record", "historical", "evidence", "resource"}
AUTHORITIES = {
    "navigation", "status", "architecture", "roadmap", "scope", "charter",
    "workflow", "code-boundaries", "security", "delivery", "testing",
}


def managed_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "--cached",
         "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return sorted({
        p for p in result.stdout.decode("utf-8").split("\0")
        if PurePosixPath(p).suffix.lower() in {".md", ".txt"}
    })


def safe_path(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or any(ord(c) < 32 for c in relative)):
        raise ValueError("invalid repository path")
    p = PurePosixPath(relative)
    if p.is_absolute() or ".." in p.parts or p.as_posix() != relative:
        raise ValueError("non-canonical repository path")
    target = root.joinpath(*p.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("path escapes repository")
    if target.is_symlink():
        raise ValueError("document symlink is not permitted")
    return target


def without_fences(content: str) -> str:
    lines, marker = [], None
    for line in content.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker is None and match:
            marker = match.group(1)
        elif marker is not None and re.match(
                r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", line):
            marker = None
        elif marker is None:
            lines.append(line)
    return "\n".join(lines)


def anchors(content: str) -> set[str]:
    text = without_fences(content)
    result = set(re.findall(r'<(?:a|h[1-6])\b[^>]*\b(?:id|name)=["\x27]([^"\x27]+)', text, re.I))
    duplicates: Counter[str] = Counter()
    headings = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        atx = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if atx:
            headings.append(atx.group(1))
        elif index and re.match(r"^ {0,3}(?:=+|-+)\s*$", line) and lines[index - 1].strip():
            headings.append(lines[index - 1].strip())
    for heading in headings:
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = "".join(
            c for c in heading if c in " -_" or unicodedata.category(c)[0] in "LNM"
        ).replace(" ", "-")
        count = duplicates[slug]
        duplicates[slug] += 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def markdown_links(content: str) -> list[str]:
    text = re.sub(r"(`+).*?\1", "", without_fences(content))
    inline = re.findall(
        r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+["\x27][^\n]*?["\x27])?\s*\)',
        text,
    )
    definitions = re.findall(
        r"^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", text, re.M,
    )
    return [item[1:-1] if item.startswith("<") else item for item in inline + definitions]


def check_repository(root: Path, paths: list[str] | None = None) -> dict:
    root = root.resolve()
    errors = []
    try:
        register = json.loads((root / REGISTER).read_text(encoding="utf-8-sig"))
        actual = set(managed_paths(root) if paths is None else paths)
        if register["schema_version"] != "enterprise-documents-v1":
            raise ValueError("unsupported register schema")
        date.fromisoformat(register["reviewed_at"])
        if not re.fullmatch(r"[0-9a-f]{40}", register["audit_base_commit"]):
            raise ValueError("invalid audit commit")
        entries = register["documents"]
        if not isinstance(entries, list):
            raise ValueError("documents must be an array")
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        return {"ok": False, "documents": 0, "errors": [f"register/Git: {exc}"]}

    seen, roles, contents = set(), {}, {}
    frozen_count = local_links = 0
    for item in entries:
        try:
            path = item["path"]
            file = safe_path(root, path)
            if file.suffix.lower() not in {".md", ".txt"}:
                raise ValueError("not a managed documentation suffix")
            if path in seen:
                errors.append(f"duplicate registration: {path}")
            seen.add(path)
            if item["kind"] not in KINDS:
                raise ValueError("unknown document kind")
            if not file.is_file():
                raise ValueError("document does not exist")
            data = file.read_bytes()
            content = data.decode("utf-8-sig")
            contents[path] = content
            if item["kind"] == "authority":
                role = item["authority"]
                if role not in AUTHORITIES:
                    raise ValueError("unknown authority purpose")
                if role in roles:
                    errors.append(f"duplicate authority: {role}")
                roles[role] = path
                reviewed = item["reviewed_at"]
                date.fromisoformat(reviewed)
                if reviewed > register["reviewed_at"]:
                    raise ValueError("authority date exceeds audit date")
                header_dates = re.findall(
                    r"(?:更新时间|更新日期|日期|Reviewed)\s*[:：]\s*(\d{4}-\d{2}-\d{2})",
                    content[:1600],
                )
                if reviewed not in header_dates:
                    errors.append(f"authority review date missing/mismatched: {path}")
            elif "authority" in item:
                errors.append(f"non-authority declares purpose: {path}")
            if "frozen_sha256" in item:
                frozen_count += 1
                expected = item["frozen_sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("invalid frozen hash")
                # Git text checkout may use CRLF on Windows and LF in CI.
                if hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest() != expected:
                    errors.append(f"frozen content changed: {path}")
            replacements = item.get("superseded_by", [])
            if not isinstance(replacements, list):
                raise ValueError("superseded_by must be an array")
            header_targets = []
            for link in markdown_links(content[:1800]):
                parts = urlsplit(link)
                if not parts.scheme and not parts.netloc:
                    header_targets.append((file.parent / unquote(parts.path)).resolve())
            for replacement in replacements:
                target = safe_path(root, replacement)
                if not target.is_file():
                    errors.append(f"replacement missing: {path} -> {replacement}")
                if target.resolve() not in header_targets:
                    errors.append(f"replacement header missing: {path} -> {replacement}")
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"invalid document entry {item.get('path', '?') if isinstance(item, dict) else '?'}: {exc}")

    errors += [f"unregistered document: {p}" for p in sorted(actual - seen)]
    errors += [f"registered but not managed: {p}" for p in sorted(seen - actual)]
    if set(roles) != AUTHORITIES:
        errors.append("authority purposes missing: " + ", ".join(sorted(AUTHORITIES - set(roles))))

    anchor_cache = {}
    for path, content in contents.items():
        if not path.endswith(".md"):
            continue
        source = root / path
        for link in markdown_links(content):
            try:
                parts = urlsplit(link)
                if parts.scheme or parts.netloc:
                    continue  # Never fetch external URLs or interpret app deep links.
                decoded = unquote(parts.path)
                if "\\" in decoded or ":" in decoded:
                    raise ValueError("invalid local link path")
                target = (source.parent / decoded).resolve() if decoded else source
                if not target.is_relative_to(root):
                    raise ValueError("local link escapes repository")
                local_links += 1
                if not target.exists():
                    errors.append(f"local link missing: {path} -> {link}")
                    continue
                if parts.fragment and target.suffix.lower() == ".md":
                    if target not in anchor_cache:
                        anchor_cache[target] = anchors(target.read_text(encoding="utf-8-sig"))
                    if unquote(parts.fragment) not in anchor_cache[target]:
                        errors.append(f"local anchor missing: {path} -> {link}")
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f"invalid local link: {path} -> {link}: {exc}")
    return {
        "ok": not errors, "documents": len(seen), "authorities": len(roles),
        "frozen_documents": frozen_count, "local_links": local_links,
        "kinds": dict(sorted(Counter(item.get("kind", "?") for item in entries if isinstance(item, dict)).items())),
        "errors": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = check_repository(args.root)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
