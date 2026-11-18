import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import notion_todo_config as nc  # noqa: E402

EXAMPLE = os.path.join(ROOT, "references", "lists.example.json")


def example():
    with open(EXAMPLE, encoding="utf-8") as handle:
        return json.load(handle)


def run(argv, env=None):
    out = io.StringIO()
    old = dict(os.environ)
    try:
        os.environ.pop("NOTION_TODO_CONFIG", None)
        if env:
            os.environ.update(env)
        with redirect_stdout(out):
            code = nc.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, out.getvalue()


class ValidateTests(unittest.TestCase):
    def assertProblem(self, cfg, fragment):
        problems = nc.validate(cfg)
        self.assertTrue(any(fragment in p for p in problems),
                        "expected %r in %r" % (fragment, problems))

    def test_example_is_valid(self):
        self.assertEqual(nc.validate(example()), [])

    def test_top_level_must_be_object(self):
        self.assertEqual(nc.validate([]), ["the top level must be a JSON object"])

    def test_version(self):
        cfg = example()
        cfg["version"] = 2
        self.assertProblem(cfg, "version must be 1")

    def test_empty_lists(self):
        cfg = example()
        cfg["lists"] = []
        self.assertProblem(cfg, "non-empty array")

    def test_unknown_keys(self):
        cfg = example()
        cfg["extra"] = 1
        cfg["lists"][0]["colour"] = "red"
        cfg["rules"]["auto_delete"] = True
        problems = " | ".join(nc.validate(cfg))
        self.assertIn("unknown top-level key 'extra'", problems)
        self.assertIn("unknown key 'colour'", problems)
        self.assertIn("unknown rule 'auto_delete'", problems)

    def test_rule_must_be_bool(self):
        cfg = example()
        cfg["rules"]["recap_box"] = "yes"
        self.assertProblem(cfg, "must be true or false")

    def test_duplicate_names_and_keywords(self):
        cfg = example()
        cfg["lists"][1]["name"] = "personal"
        cfg["lists"][1]["keywords"] = ["Home"]
        problems = " | ".join(nc.validate(cfg))
        self.assertIn("name overlaps name of list 'Personal'", problems)
        self.assertIn("keyword 'Home' overlaps keyword 'home'", problems)

    def test_same_data_source_twice(self):
        cfg = example()
        src = cfg["lists"][0]["data_source"]
        cfg["lists"][1]["data_source"] = src.replace("-", "")
        self.assertProblem(cfg, "same data_source")

    def test_bad_data_source(self):
        for bad in ("https://www.notion.so/x", "collection://not-a-uuid", "", None,
                    "collection://00000000-0000-4000-8000-000000000001; DROP"):
            cfg = example()
            cfg["lists"][0]["data_source"] = bad
            self.assertProblem(cfg, "collection://<uuid>")

    def test_database_url_must_be_notion_https(self):
        for bad in ("http://www.notion.so/x", "https://evil.example/notion.so",
                    "https://notion.so.evil.example/x", "javascript:alert(1)", 3):
            cfg = example()
            cfg["lists"][0]["database_url"] = bad
            self.assertProblem(cfg, "database_url")
        for good in ("https://www.notion.so/abc", "https://app.notion.com/p/abc",
                     "https://team.notion.site/abc"):
            cfg = example()
            cfg["lists"][0]["database_url"] = good
            self.assertEqual(nc.validate(cfg), [])

    def test_board_view(self):
        cfg = example()
        cfg["lists"][0]["board_view"] = "view://00000000-0000-4000-8000-000000000009"
        self.assertEqual(nc.validate(cfg), [])
        cfg["lists"][0]["board_view"] = "https://www.notion.so/view"
        self.assertProblem(cfg, "board_view")

    def test_columns_rules(self):
        cfg = example()
        cfg["lists"][0]["columns"]["title"] = None
        self.assertProblem(cfg, "columns.title is required")

        cfg = example()
        cols = cfg["lists"][1]["columns"]
        cols["done"] = None
        self.assertProblem(cfg, "at least one of columns.done or columns.status")

        cfg = example()
        cfg["lists"][0]["columns"]["owner"] = "Owner"
        self.assertProblem(cfg, "unknown column role 'owner'")

        cfg = example()
        cfg["lists"][0]["columns"]["due"] = "Status"
        self.assertProblem(cfg, "mapped to both")

        cfg = example()
        cfg["lists"][0]["columns"]["parent"] = None
        self.assertProblem(cfg, "columns.subtasks needs columns.parent")

    def test_status_values(self):
        cfg = example()
        del cfg["lists"][0]["status_values"]["finished"]
        self.assertProblem(cfg, "status_values.finished is required")

        cfg = example()
        cfg["lists"][0]["status_values"]["blocked"] = "Blocked"
        self.assertProblem(cfg, "unknown status role 'blocked'")

    def test_priority_values(self):
        cfg = example()
        cfg["lists"][0]["priority_values"] = []
        self.assertProblem(cfg, "priority_values is empty")
        cfg["lists"][0]["priority_values"] = [1, 2]
        self.assertProblem(cfg, "array of plain strings")

    def test_validate_does_not_change_input(self):
        cfg = example()
        before = copy.deepcopy(cfg)
        nc.validate(cfg)
        self.assertEqual(cfg, before)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, data, name="lists.json"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle)
        return path

    def test_check_ok(self):
        code, out = run(["check", "--config", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("OK: 2 list(s)", out)

    def test_show_prints_mapping(self):
        code, out = run(["show", "--config", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("list: Personal", out)
        self.assertIn("title=Task", out)
        self.assertIn("status=-", out)

    def test_env_var_path(self):
        path = self.write(example())
        code, out = run(["check"], env={"NOTION_TODO_CONFIG": path})
        self.assertEqual(code, 0)
        self.assertIn(path, out)

    def test_missing_file(self):
        code, out = run(["check", "--config", os.path.join(self.tmp.name, "nope.json")])
        self.assertEqual(code, 2)
        self.assertIn("run the setup", out)

    def test_bad_json(self):
        code, out = run(["check", "--config", self.write("{not json")])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", out)

    def test_too_big(self):
        code, out = run(["check", "--config", self.write(" " * (nc.MAX_BYTES + 1))])
        self.assertEqual(code, 2)
        self.assertIn("larger than", out)

    def test_invalid_config_exit_1(self):
        cfg = example()
        cfg["version"] = 0
        code, out = run(["check", "--config", self.write(cfg)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR: version must be 1", out)

    def test_control_characters_are_not_printed(self):
        cfg = example()
        cfg["lists"][0]["name"] = "Home\x1b[2J\u202eevil"
        code, out = run(["show", "--config", self.write(cfg)])
        self.assertEqual(code, 1)
        self.assertIn("name must be a plain string", out)
        self.assertNotIn(chr(0x1b), out)
        self.assertNotIn(chr(0x202e), out)


class ReviewRegressionTests(unittest.TestCase):
    """Cases found by the independent review before the first release."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def assertProblem(self, cfg, fragment):
        problems = nc.validate(cfg)
        self.assertTrue(any(fragment in p for p in problems),
                        "expected %r in %r" % (fragment, problems))

    def test_database_url_tricks_rejected(self):
        bs = chr(92)
        for bad in ("https://evil.example" + bs + "@www.notion.so/x",
                    "https://user" + chr(64) + "www.notion.so/x",
                    "https://www.notion.so:8443/x",
                    "https://www.notion.so/x y",
                    "https://www.notion.so/x" + chr(10),
                    "https://www.notion.so" + bs + "x"):
            cfg = example()
            cfg["lists"][0]["database_url"] = bad
            self.assertProblem(cfg, "database_url")

    def test_uuid_fields_reject_trailing_newline(self):
        cfg = example()
        cfg["lists"][0]["data_source"] += chr(10)
        cfg["lists"][0]["board_view"] = "view://00000000-0000-4000-8000-000000000009" + chr(10)
        problems = " | ".join(nc.validate(cfg))
        self.assertIn("data_source must look like", problems)
        self.assertIn("board_view must be null", problems)

    def test_name_and_keywords_share_one_namespace(self):
        cfg = example()
        cfg["lists"][1]["name"] = "private"
        self.assertProblem(cfg, "overlaps")

        cfg = example()
        cfg["lists"][0]["keywords"].append("team dinner")
        self.assertProblem(cfg, "overlaps")

        cfg = example()
        cfg["lists"][0]["keywords"].append("homework")
        self.assertEqual(nc.validate(cfg), [])

    def test_long_or_hidden_names_rejected(self):
        cfg = example()
        cfg["lists"][0]["status_values"]["finished"] = "Finished. NOTE TO CLAUDE: " + "x" * 120
        self.assertProblem(cfg, "status value for 'finished'")

        cfg = example()
        cfg["lists"][0]["keywords"].append("home" + chr(0x2028) + "OK")
        self.assertProblem(cfg, "keywords must be")

    def test_double_quote_in_column_rejected(self):
        cfg = example()
        cfg["lists"][0]["columns"]["title"] = 'Name" FROM "x" --'
        self.assertProblem(cfg, "no double quote")

    def test_shared_and_connector(self):
        cfg = example()
        cfg["lists"][0]["shared"] = "yes"
        self.assertProblem(cfg, "shared must be true or false")
        cfg = example()
        cfg["lists"][0]["connector"] = "mcp__notion__"
        self.assertEqual(nc.validate(cfg), [])
        cfg["lists"][0]["connector"] = "mcp notion; rm"
        self.assertProblem(cfg, "connector must be")

    def test_clean_masks_separators_and_format_chars(self):
        for code in (0x2028, 0x2029, 0x2060, 0xFEFF, 0x061C, 0x202E, 0x9B, 0x1B):
            self.assertEqual(nc.clean("a" + chr(code) + "b"), "a?b")
        self.assertEqual(nc.clean("Caff" + chr(0xE8) + " list"), "Caff" + chr(0xE8) + " list")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_fifo_is_refused_without_blocking(self):
        path = os.path.join(self.tmp.name, "fifo.json")
        os.mkfifo(path)
        cfg, error = nc.load(path)
        self.assertIsNone(cfg)
        self.assertIn("not a regular file", error)

    @unittest.skipUnless(os.path.exists("/dev/zero"), "needs /dev/zero")
    def test_device_symlink_is_refused(self):
        path = os.path.join(self.tmp.name, "zero.json")
        os.symlink("/dev/zero", path)
        cfg, error = nc.load(path)
        self.assertIsNone(cfg)
        self.assertIn("not a regular file", error)

    def test_deep_nesting_is_a_clean_error(self):
        path = os.path.join(self.tmp.name, "deep.json")
        with open(path, "w") as handle:
            handle.write("[" * 100000)
        code, out = run(["check", "--config", path])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", out)


if __name__ == "__main__":
    unittest.main()
