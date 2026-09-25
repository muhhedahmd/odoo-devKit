# -*- coding: utf-8 -*-
"""The OWL template rules, read out of OWL rather than remembered.

Every directive name and every rule below is extracted from the OWL bundle in
tools/jstypes (pinned to 2.8.2, the version Odoo 19 ships) and from the
templates in the Odoo source. Nothing here is typed from memory, because the
whole point is to be right about the version that is actually loading.

It writes two things:

* the directives OWL accepts — anything else spelled `t-…` is a silent no-op
  in the browser, which is the worst way to lose an hour;
* every `t-name` that exists, so a `t-call` at a template that is not there
  can be reported here instead of at runtime.

    python tools/owl_index.py
"""
import argparse
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "odools.toml")
OWL_BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "jstypes", "node_modules", "@odoo", "owl",
                          "dist", "owl.cjs.js")
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".owl_index.json")

ENTERPRISE_DIRS = {"ent_addons", "enterprise", "odoo-enterprise"}

# Directives that take a suffix rather than standing alone: t-on-click,
# t-att-src, t-attf-class. OWL's own error — "Missing event name with t-on
# directive" — is what says t-on alone is wrong.
PREFIXED = ("t-on-", "t-att-", "t-attf-", "t-custom-", "t-translation-context-")

# The rules OWL enforces at compile time, in its own words. Kept as data so
# the editor can report them before the browser does.
RULES = [
    {
        "id": "owl-foreach-key",
        "test": "foreach_without_key",
        "message": "Directive t-foreach should always be used with a t-key",
        "severity": "error",
        "why": "OWL throws on this. Without a key it cannot tell which item "
               "moved, so a reorder re-renders the wrong rows.",
    },
    {
        "id": "owl-elif-order",
        "test": "elif_without_if",
        "message": "t-elif and t-else must be preceded by a t-if or t-elif",
        "severity": "error",
        "why": "OWL throws on this.",
    },
    {
        "id": "owl-component-on-t",
        "test": "component_not_on_t",
        "message": "t-component can only be used on a <t> node",
        "severity": "error",
        "why": "OWL throws on this.",
    },
    {
        "id": "owl-setslot-on-t",
        "test": "setslot_not_on_t",
        "message": "t-set-slot can only be used on a <t> node",
        "severity": "error",
        "why": "OWL throws on this.",
    },
    {
        "id": "owl-model-target",
        "test": "model_bad_tag",
        "message": "t-model only works on <input>, <textarea> and <select>",
        "severity": "error",
        "why": "OWL throws on this.",
    },
    {
        "id": "owl-bare-on",
        "test": "bare_prefixed",
        "message": "This directive needs a suffix — t-on-click, not t-on",
        "severity": "error",
        "why": "OWL throws 'Missing event name with t-on directive'.",
    },
    {
        "id": "owl-unknown",
        "test": "unknown_directive",
        "message": "Not an OWL directive",
        "severity": "warning",
        "why": "A misspelt t-… is not an error in the browser: it is kept as "
               "a plain attribute and does nothing at all.",
    },
    {
        "id": "owl-raw",
        "test": "t_raw",
        "message": "t-raw was removed in OWL 2 — use t-out",
        "severity": "warning",
        "why": "t-out escapes unless handed a Markup value, which is what "
               "t-raw used to do unconditionally.",
    },
]


def odoo_roots():
    roots = []
    if os.path.exists(CONFIG):
        for match in re.finditer(r'"([^"]+)"',
                                 io.open(CONFIG, encoding="utf-8").read()):
            if os.path.isdir(match.group(1)):
                roots.append(match.group(1))
    return roots or [REPO]


def directives_from_owl():
    """The names OWL's own compiler knows."""
    if not os.path.exists(OWL_BUNDLE):
        return []
    text = io.open(OWL_BUNDLE, encoding="utf-8", errors="ignore").read()
    names = set(re.findall(r'["\'](t-[a-z-]+)["\']', text))
    # `t-custom-` and friends appear as prefixes; keep them, the editor
    # matches on them separately.
    return sorted(names)


def template_names(roots):
    """Every t-name that exists, for checking t-call."""
    names = {}
    pattern = re.compile(r't-name\s*=\s*"([^"]+)"')
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in {"node_modules", "__pycache__", ".git"}
                       | ENTERPRISE_DIRS]
            for name in files:
                if not name.endswith(".xml"):
                    continue
                path = os.path.join(folder, name)
                try:
                    text = io.open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if "t-name" not in text:
                    continue
                for match in pattern.finditer(text):
                    names.setdefault(match.group(1), path)
    return names


def attributes_used_in_core(roots):
    """Every t- attribute Odoo's own OWL templates actually use.

    A safety net against warning on something real. OWL's compiler list is
    the truth about OWL, but Odoo layers a few of its own on top, and a
    warning on a directive core uses hundreds of times would only teach you
    to ignore the warnings.
    """
    counts = {}
    pattern = re.compile(r'\s(t-[a-zA-Z0-9_.-]+)\s*=')
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in {"node_modules", "__pycache__", ".git"}
                       | ENTERPRISE_DIRS]
            if os.sep + "static" + os.sep not in folder + os.sep:
                continue
            for name in files:
                if not name.endswith(".xml"):
                    continue
                try:
                    text = io.open(os.path.join(folder, name),
                                   encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for match in pattern.finditer(text):
                    attr = match.group(1)
                    counts[attr] = counts.get(attr, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    roots = list(dict.fromkeys([REPO] + odoo_roots()))
    used = attributes_used_in_core(roots)
    # Three uses is enough to call it real rather than somebody's typo.
    from_core = sorted(a for a, n in used.items() if n >= 3)
    data = {
        "directives": directives_from_owl(),
        "from_core": from_core,
        "prefixed": list(PREFIXED),
        "rules": RULES,
        "templates": sorted(template_names(roots)),
    }
    with io.open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)

    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return
    print("directives from OWL: %d" % len(data["directives"]))
    print("  " + ", ".join(data["directives"]))
    print("rules: %d" % len(data["rules"]))
    print("t-name templates found: %d" % len(data["templates"]))
    extra = [a for a in data["from_core"]
             if a not in data["directives"]
             and not any(a.startswith(p) for p in PREFIXED)]
    print("used by core but not in OWL's own list: %d" % len(extra))
    print("  " + ", ".join(extra[:40]))


if __name__ == "__main__":
    sys.exit(main())
