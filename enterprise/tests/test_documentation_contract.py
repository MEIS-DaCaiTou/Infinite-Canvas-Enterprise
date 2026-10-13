"""Documentation checks use disposable files, never product/customer roots."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "ice_check_docs", Path(__file__).resolve().parents[2] / "tools" / "check_docs.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class DocumentationContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ice-doc-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.entries = []
        for role in sorted(CHECKER.AUTHORITIES):
            path = f"docs/{role}.md"
            self.write(path, f"# {role}\n\nReviewed: 2026-10-03\n")
            self.entries.append({"path": path, "kind": "authority",
                                 "authority": role, "reviewed_at": "2026-10-03"})
        self.paths = [e["path"] for e in self.entries]

    def write(self, path, content):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")

    def add(self, path, content, **metadata):
        self.write(path, content)
        self.entries.append({"path": path, "kind": "reference", **metadata})
        self.paths.append(path)

    def report(self):
        self.write(CHECKER.REGISTER, json.dumps({
            "schema_version": "enterprise-documents-v1", "reviewed_at": "2026-10-03",
            "audit_base_commit": "a" * 40, "documents": self.entries,
        }, ensure_ascii=False))
        return CHECKER.check_repository(self.root, self.paths)

    def assert_error(self, fragment):
        report = self.report()
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(fragment in error for error in report["errors"]), report)

    def test_valid_and_unicode_heading(self):
        self.add("docs/中文.md", "# 中文\n\n## 5. 阶段 3：统一安装与更新\n")
        self.add("docs/link.md", "[中文](中文.md#5-阶段-3统一安装与更新)\n")
        report = self.report()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["local_links"], 1)

    def test_unregistered(self):
        self.write("extra.md", "# extra\n")
        self.paths.append("extra.md")
        self.assert_error("unregistered document")

    def test_missing_managed(self):
        self.entries.append({"path": "gone.md", "kind": "record"})
        self.assert_error("document does not exist")

    def test_duplicate_registration(self):
        self.entries.append(dict(self.entries[0]))
        self.assert_error("duplicate registration")

    def test_unknown_kind(self):
        self.entries[0]["kind"] = "current-facts-again"
        self.assert_error("unknown document kind")

    def test_duplicate_authority(self):
        self.add("docs/copy.md", "# Copy\nReviewed: 2026-10-03\n",
                 kind="authority", authority="status", reviewed_at="2026-10-03")
        self.assert_error("duplicate authority")

    def test_missing_authority(self):
        self.entries = [e for e in self.entries if e["authority"] != "status"]
        self.assert_error("authority purposes missing")

    def test_review_date_mismatch(self):
        self.entries[0]["reviewed_at"] = "2026-10-02"
        self.assert_error("authority review date missing/mismatched")

    def test_missing_link(self):
        self.add("docs/link.md", "[bad](missing.md)\n")
        self.assert_error("local link missing")

    def test_missing_anchor(self):
        self.add("docs/link.md", "[bad](status.md#missing)\n")
        self.assert_error("local anchor missing")

    def test_fences_inline_code_external_and_reference(self):
        self.add("docs/link.md", "\n".join([
            "```md", "[ignore](gone.md)", "```", "`[ignore](gone.md)`",
            "[external](https://example.invalid/)", "[status][s]", "[s]: status.md",
        ]))
        report = self.report()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["local_links"], 1)

    def test_space_and_duplicate_anchor(self):
        self.add("docs/two headings.md", "# repeat\n\n## repeat\n")
        self.add("docs/link.md", "[second](<two headings.md#repeat-1>)\n")
        self.assertTrue(self.report()["ok"])

    def test_escaping_link(self):
        self.add("docs/link.md", "[escape](../../outside.md)\n")
        self.assert_error("escapes repository")

    def test_invalid_registration_path(self):
        self.entries.append({"path": "../escape.md", "kind": "record"})
        self.assert_error("non-canonical repository path")

    def test_frozen_content_and_mutation(self):
        self.add("docs/evidence.md", "# frozen\n", kind="evidence",
                 frozen_sha256=hashlib.sha256(b"# frozen\n").hexdigest())
        self.assertTrue(self.report()["ok"])
        self.write("docs/evidence.md", "# rewritten\n")
        self.assert_error("frozen content changed")

    def test_replacement_header(self):
        self.add("docs/old.md", "# old\n", kind="historical",
                 superseded_by=["docs/status.md"])
        self.assert_error("replacement header missing")
        self.write("docs/old.md", "# old\n\n> Replaced by [status](status.md).\n")
        self.assertTrue(self.report()["ok"])

    def test_bad_register_fails_closed(self):
        self.write(CHECKER.REGISTER, "{not-json")
        self.assertFalse(CHECKER.check_repository(self.root, self.paths)["ok"])


if __name__ == "__main__":
    unittest.main()
