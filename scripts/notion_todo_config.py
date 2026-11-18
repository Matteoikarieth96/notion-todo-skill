#!/usr/bin/env python3
"""Check and print the notion-todo config (which Notion lists, which columns).

Usage:
  python3 notion_todo_config.py check [--config PATH]
  python3 notion_todo_config.py show  [--config PATH]

The config path is --config, else $NOTION_TODO_CONFIG, else
~/.claude/notion-todo/lists.json. Standard library only; no network.
Exit code 0 when the config is valid, 1 when it has problems, 2 when it is
missing or unreadable.
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

DEFAULT_PATH = os.path.join("~", ".claude", "notion-todo", "lists.json")
ROLES = ("title", "status", "priority", "due", "done", "parent", "subtasks")
STATUS_ROLES = ("not_started", "in_progress", "waiting", "backlog", "finished", "archived")
RULES = ("done_sets_status", "recap_box")
LIST_KEYS = ("name", "keywords", "data_source", "database_url", "board_view",
             "day_note", "columns", "status_values", "priority_values")
UUID = r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"
DATA_SOURCE_RE = re.compile(r"^collection://" + UUID + r"$")
VIEW_RE = re.compile(r"^view://" + UUID + r"$")
NOTION_HOSTS = ("notion.so", "notion.com", "notion.site")
MAX_BYTES = 256 * 1024
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def config_path(cli_path=None):
    path = cli_path or os.environ.get("NOTION_TODO_CONFIG") or DEFAULT_PATH
    return os.path.expanduser(path)


def clean(text):
    """Make a config value safe to print in a terminal."""
    return CONTROL_RE.sub("?", str(text))


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _notion_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in NOTION_HOSTS)


def _norm_uuid(text):
    return re.sub(r"[^0-9a-f]", "", text.lower().split("://", 1)[-1])


def validate(cfg):
    """Return a list of problems (empty when the config is valid)."""
    errors = []
    if not isinstance(cfg, dict):
        return ["the top level must be a JSON object"]
    for key in cfg:
        if key not in ("version", "rules", "lists"):
            errors.append("unknown top-level key %r" % key)
    if cfg.get("version") != 1:
        errors.append("version must be 1")

    rules = cfg.get("rules", {})
    if not isinstance(rules, dict):
        errors.append("rules must be an object")
    else:
        for key, value in rules.items():
            if key not in RULES:
                errors.append("unknown rule %r (known: %s)" % (key, ", ".join(RULES)))
            elif not isinstance(value, bool):
                errors.append("rule %r must be true or false" % key)

    lists = cfg.get("lists")
    if not isinstance(lists, list) or not lists:
        errors.append("lists must be a non-empty array")
        return errors

    names, keywords, sources = {}, {}, {}
    for i, item in enumerate(lists, 1):
        where = "list %d" % i
        if not isinstance(item, dict):
            errors.append("%s must be an object" % where)
            continue
        if _is_text(item.get("name")):
            where = "list %r" % item["name"]
        for key in item:
            if key not in LIST_KEYS:
                errors.append("%s: unknown key %r" % (where, key))

        name = item.get("name")
        if not _is_text(name):
            errors.append("%s: name must be a non-empty string" % where)
        else:
            low = name.strip().lower()
            if low in names:
                errors.append("%s: same name as another list" % where)
            names[low] = where

        kws = item.get("keywords")
        if not isinstance(kws, list) or not kws or not all(_is_text(k) for k in kws):
            errors.append("%s: keywords must be a non-empty array of strings" % where)
        else:
            for kw in kws:
                low = kw.strip().lower()
                other = keywords.get(low)
                if other and other != where:
                    errors.append("%s: keyword %r is also used by %s" % (where, kw, other))
                keywords[low] = where

        src = item.get("data_source")
        if not isinstance(src, str) or not DATA_SOURCE_RE.match(src):
            errors.append("%s: data_source must look like collection://<uuid>" % where)
        else:
            key = _norm_uuid(src)
            if key in sources:
                errors.append("%s: same data_source as %s" % (where, sources[key]))
            sources[key] = where

        if not _notion_url(item.get("database_url")):
            errors.append("%s: database_url must be an https link on a Notion domain" % where)

        view = item.get("board_view")
        if view is not None and (not isinstance(view, str) or not VIEW_RE.match(view)):
            errors.append("%s: board_view must be null or view://<uuid>" % where)

        if "day_note" in item and not isinstance(item["day_note"], bool):
            errors.append("%s: day_note must be true or false" % where)

        cols = item.get("columns")
        if not isinstance(cols, dict):
            errors.append("%s: columns must be an object" % where)
        else:
            seen = {}
            for role, col in cols.items():
                if role not in ROLES:
                    errors.append("%s: unknown column role %r (known: %s)" % (where, role, ", ".join(ROLES)))
                    continue
                if col is None:
                    continue
                if not _is_text(col):
                    errors.append("%s: column for %r must be a name or null" % (where, role))
                    continue
                if col in seen:
                    errors.append("%s: column %r is mapped to both %r and %r" % (where, col, seen[col], role))
                seen[col] = role
            if not _is_text(cols.get("title")):
                errors.append("%s: columns.title is required" % where)
            if not cols.get("done") and not cols.get("status"):
                errors.append("%s: map at least one of columns.done or columns.status" % where)
            if cols.get("subtasks") and not cols.get("parent"):
                errors.append("%s: columns.subtasks needs columns.parent" % where)

        sv = item.get("status_values", {})
        if not isinstance(sv, dict):
            errors.append("%s: status_values must be an object" % where)
        else:
            for role, value in sv.items():
                if role not in STATUS_ROLES:
                    errors.append("%s: unknown status role %r (known: %s)" % (where, role, ", ".join(STATUS_ROLES)))
                elif not _is_text(value):
                    errors.append("%s: status value for %r must be a string" % (where, role))
            if isinstance(cols, dict) and cols.get("status") and "finished" not in sv:
                errors.append("%s: status_values.finished is required when a status column is mapped" % where)

        pv = item.get("priority_values", [])
        if not isinstance(pv, list) or not all(_is_text(p) for p in pv):
            errors.append("%s: priority_values must be an array of strings" % where)
        elif isinstance(cols, dict) and cols.get("priority") and not pv:
            errors.append("%s: priority_values is empty but a priority column is mapped" % where)
    return errors


def load(path):
    """Return (config, error). error is None on success."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, "no config at %s: run the setup in references/setup.md" % path
    if size > MAX_BYTES:
        return None, "config is larger than %d bytes: %s" % (MAX_BYTES, path)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def summary(cfg):
    lines = []
    rules = cfg.get("rules", {})
    lines.append("rules: done_sets_status=%s recap_box=%s" % (
        rules.get("done_sets_status", False), rules.get("recap_box", True)))
    for item in cfg["lists"]:
        lines.append("")
        lines.append("list: %s" % clean(item["name"]))
        lines.append("  keywords: %s" % ", ".join(clean(k) for k in item["keywords"]))
        lines.append("  data_source: %s" % clean(item["data_source"]))
        lines.append("  database_url: %s" % clean(item["database_url"]))
        if item.get("board_view"):
            lines.append("  board_view: %s" % clean(item["board_view"]))
        lines.append("  day_note: %s" % bool(item.get("day_note", False)))
        cols = item["columns"]
        lines.append("  columns: " + ", ".join(
            "%s=%s" % (role, clean(cols[role]) if cols.get(role) else "-") for role in ROLES))
        sv = item.get("status_values", {})
        if sv:
            lines.append("  status: " + ", ".join(
                "%s=%s" % (role, clean(sv[role])) for role in STATUS_ROLES if role in sv))
        if item.get("priority_values"):
            lines.append("  priority (high to low): " + ", ".join(clean(p) for p in item["priority_values"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check or print the notion-todo config.")
    parser.add_argument("command", choices=("check", "show"))
    parser.add_argument("--config", help="config path (default: $NOTION_TODO_CONFIG or %s)" % DEFAULT_PATH)
    args = parser.parse_args(argv)

    path = config_path(args.config)
    cfg, error = load(path)
    if error:
        print("ERROR: " + clean(error))
        return 2
    problems = validate(cfg)
    if problems:
        print("config: %s" % clean(path))
        for problem in problems:
            print("ERROR: " + clean(problem))
        return 1
    if args.command == "show":
        print("config: %s" % clean(path))
        print(summary(cfg))
    else:
        print("OK: %d list(s) in %s" % (len(cfg["lists"]), clean(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
