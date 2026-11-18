import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_EXT = (".md", ".json", ".py", ".yml", ".txt")
PLACEHOLDER_UUID = re.compile(r"^0{8}-?0{4}-?4000-?8000-?0{11}\d$")
UUID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}(?![0-9a-f])", re.I)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def frontmatter():
    text = read("SKILL.md")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md has no frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, text[match.end():]


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith(TEXT_EXT) or name in ("LICENSE", ".gitignore"):
                path = os.path.join(base, name)
                yield os.path.relpath(path, ROOT)


class SkillTests(unittest.TestCase):
    def test_frontmatter(self):
        fields, body = frontmatter()
        self.assertEqual(set(fields), {"name", "description"})
        self.assertEqual(fields["name"], "notion-todo")
        self.assertRegex(fields["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertNotIn("<", fields["description"])
        self.assertNotIn(">", fields["description"])
        self.assertLess(len(body.splitlines()), 500)

    def test_links_to_local_files_exist(self):
        for rel in ("SKILL.md", "README.md", "references/setup.md", "SECURITY.md"):
            for target in re.findall(r"\]\(([^)#]+)\)", read(rel)):
                if "://" in target:
                    continue
                path = os.path.normpath(os.path.join(ROOT, os.path.dirname(rel), target))
                self.assertTrue(os.path.exists(path), "%s links to missing %s" % (rel, target))

    def test_skill_points_to_script_and_setup(self):
        _, body = frontmatter()
        self.assertIn("scripts/notion_todo_config.py", body)
        self.assertIn("references/setup.md", body)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "scripts", "notion_todo_config.py")))

    def test_no_dashes_or_hidden_unicode(self):
        hidden = re.compile("[\u2013\u2014\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
        for rel in text_files():
            match = hidden.search(read(rel))
            self.assertIsNone(match, "%s contains %r" % (rel, match and match.group()))

    def test_only_placeholder_ids(self):
        for rel in text_files():
            if rel.startswith("tests" + os.sep):
                continue
            for found in UUID_RE.findall(read(rel)):
                self.assertRegex(found, PLACEHOLDER_UUID,
                                 "%s contains a non-placeholder id %s" % (rel, found))

    def test_trigger_evals(self):
        data = json.loads(read("evals/trigger_evals.json"))
        self.assertGreaterEqual(len(data), 10)
        flags = [item["should_trigger"] for item in data]
        self.assertIn(True, flags)
        self.assertIn(False, flags)
        for item in data:
            self.assertEqual(set(item), {"query", "should_trigger"})
            self.assertTrue(item["query"].strip())


if __name__ == "__main__":
    unittest.main()
