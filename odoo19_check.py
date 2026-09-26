# -*- coding: utf-8 -*-
"""What Odoo 19 removed, found before the build finds it.

Every rule here is something that cost a push and a failed build on this
project. Most of them do not raise a Python error — they are accepted, and
then ignored, or they fail deep inside the view loader with a message that
names the view and not the line.

    python odoo-devkit/odoo19_check.py                 # this project
    python odoo-devkit/odoo19_check.py my_module       # one module

Each finding is printed as `path:line: message`, which editors turn into a
clickable link.
"""
import argparse
import io
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "node_modules", "__pycache__", "odoo-devkit", "i18n",
             "lib", ".vscode"}

# (pattern, files it applies to, message)
#
# The messages say what happens rather than what to do, because "removed in
# 19" is not the useful part — "accepted and then ignored" is.
RULES = [
    # Not `= []`: an empty list is somebody saying "none", and nothing is
    # being dropped.
    # The lookahead has to sit right after `=`: with `\s*` before it, the
    # regex simply backtracks to zero spaces and the lookahead never sees
    # the bracket it is there to find.
    (r"_sql_constraints\s*=(?!\s*\[\s*\])",
     ".py",
     "_sql_constraints is ignored in Odoo 19 — silently. The table gets no "
     "constraint and nothing says so. Use models.Constraint."),

    (r"\bgroup_operator\s*=",
     ".py",
     "group_operator was renamed to aggregator in 17. The old name raises on "
     "registry load."),

    (r"\bstates\s*=\s*\{",
     ".py",
     "states= on a field was removed in 17. Put the condition in the view's "
     "readonly/invisible instead."),

    (r"\bdigits\s*=\s*dp\.",
     ".py",
     "decimal_precision as dp is long gone. digits=(12, 2) or the field name "
     "of a precision."),

    (r"<group\b[^>]*\b(expand|string)\s*=",
     "search",
     "Odoo 19 removed expand= and string= from a <group> inside a search "
     "view. The error is 'Invalid view definition' and does not say which "
     "attribute."),

    (r"\bdeprecated\b\s*['\"]?\s*,\s*['\"]?=",
     ".py",
     "account.account lost `deprecated` in 19 — archiving replaced it. A "
     "domain on a field that does not exist fails view validation at "
     "install."),

    # The one that bit us: it does not fail at import, it fails at install
    # with "Invalid field 'groups_id'", and the traceback blames the XML file
    # rather than naming the rename.
    (r"""<field\s+name\s*=\s*["']groups_id["']""",
     ".xml",
     "groups_id was renamed group_ids in 19 on ir.actions.*, ir.ui.menu, "
     "res.users and res.groups. The install fails with 'Invalid field'. The "
     "groups= shorthand on a menuitem still works and is mapped for you."),

    (r"\bgroups_id\s*=",
     ".py",
     "groups_id was renamed group_ids in 19. This is the many2many itself — "
     "the `groups=` argument on a field definition is a different thing and "
     "is still correct."),

    (r"<tree\b",
     ".xml",
     "<tree> was renamed <list> in 17."),

    (r"\battrs\s*=\s*[\"']",
     ".xml",
     "attrs= was removed in 17. Write the condition directly: "
     "invisible=\"state == 'draft'\"."),

    (r"\bstates\s*=\s*[\"'][^\"']+[\"']",
     ".xml",
     "states= on a view node was removed in 17, except on a statusbar."),

    (r"t-raw\s*=",
     ".xml",
     "t-raw was removed in OWL 2 — use t-out."),

    (r"@api\.one\b|@api\.multi\b",
     ".py",
     "api.one and api.multi were removed in 13."),

    (r"\bmodules\.registry\.RegistryManager\b|\bopenerp\b",
     ".py",
     "openerp/RegistryManager are from before 10."),
]

COMPILED = [(re.compile(pattern), scope, message)
            for pattern, scope, message in RULES]

# Rules that depend on which model a <record> writes to. A pattern alone
# cannot express these: category_id is wrong on res.groups and right on
# res.groups.privilege, which is the very thing that replaced it.
RECORD = re.compile(r'<record\b[^>]*\bmodel\s*=\s*"([\w.]+)"[^>]*>', re.S)

RECORD_RULES = [
    ("res.groups", re.compile(r'<field[^>]*\bname\s*=\s*"category_id"'),
     "res.groups lost category_id in 19 — it points at a "
     "res.groups.privilege through privilege_id now. The install fails "
     "outright. (res.groups.privilege keeps a category_id of its own.)"),
]


def check_records(text, path):
    """Yield (line, message) for the rules that need the record's model."""
    if not path.endswith(".xml"):
        return
    matches = list(RECORD.finditer(text))
    for index, match in enumerate(matches):
        model = match.group(1)
        end = (matches[index + 1].start() if index + 1 < len(matches)
               else len(text))
        close = text.find("</record>", match.end())
        stop = min(end, close if close != -1 else end)
        body = text[match.end():stop]
        for wanted, pattern, message in RECORD_RULES:
            if model != wanted:
                continue
            for hit in pattern.finditer(body):
                line = text.count("\n", 0, match.end() + hit.start()) + 1
                yield line, message


def applies(rule_scope, path):
    """`.py`/`.xml` match the extension; anything else matches the path."""
    if rule_scope.startswith("."):
        return path.endswith(rule_scope)
    return rule_scope in path.replace("\\", "/")


def strip_comments(text, path):
    """Blank comments, keeping offsets: a rule found in a comment is noise."""
    if path.endswith(".xml"):
        return re.sub(r"<!--[\s\S]*?-->",
                      lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return re.sub(r"(?m)^\s*#.*$",
                  lambda m: " " * len(m.group(0)), text)


def modules(root, only):
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if only and name not in only:
            continue
        if os.path.isdir(path) and \
                os.path.exists(os.path.join(path, "__manifest__.py")):
            yield name, path


def check(root, only):
    findings = 0
    for name, folder in modules(root, only):
        for where, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                       and not d.startswith(".")]
            if os.sep + "static" + os.sep in where + os.sep:
                continue
            for filename in sorted(files):
                if not filename.endswith((".py", ".xml")):
                    continue
                path = os.path.join(where, filename)
                try:
                    text = io.open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                text = strip_comments(text, path)
                for line, message in check_records(text, path):
                    print("%s:%d: %s" % (
                        os.path.relpath(path, root).replace("\\", "/"),
                        line, message))
                    findings += 1

                for pattern, scope, message in COMPILED:
                    if not applies(scope, path):
                        continue
                    for match in pattern.finditer(text):
                        line = text.count("\n", 0, match.start()) + 1
                        print("%s:%d: %s" % (
                            os.path.relpath(path, root).replace("\\", "/"),
                            line, message))
                        findings += 1
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="*",
                        help="modules to check; all of them by default")
    args = parser.parse_args()

    found = check(REPO, set(args.modules))
    print("\n%d finding%s" % (found, "" if found == 1 else "s"))
    # Non-zero so a task or a hook can act on it.
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
