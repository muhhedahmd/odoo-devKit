# -*- coding: utf-8 -*-
"""Every `widget="..."` Odoo actually has, from the source rather than memory.

A widget name is a string. Nothing checks it: misspell `many2many_tags` and
the field silently renders as a plain one, which looks like a styling problem
and is really a typo. And a widget that exists but lives in a module you do
not depend on renders on your machine and not on the customer's.

So this reads the JS and records, for each widget, the module that registers
it and the field types it declares support for.

    python tools/widget_index.py            # rebuild, then print a summary
    python tools/widget_index.py --json     # the index itself
"""
import argparse
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "odools.toml")
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".widget_index.json")

# `registry.category("fields").add("name", descriptor)` is how every field
# widget in Odoo 17+ registers itself. View widgets (`<widget name="...">`)
# register under "view_widgets", and are collected too — the XML attribute
# is spelled the same and the mistake is the same.
ADD = re.compile(
    r'registry\s*\.\s*category\(\s*["\'](fields|view_widgets)["\']\s*\)'
    r'\s*\.\s*add\(\s*["\']([\w.\-]+)["\']',
    re.S)
SUPPORTED = re.compile(r'supportedTypes\s*:\s*\[([^\]]*)\]')
ENTERPRISE_DIRS = {"ent_addons", "enterprise", "odoo-enterprise"}


def odoo_roots():
    roots = []
    if os.path.exists(CONFIG):
        for match in re.finditer(r'"([^"]+)"', io.open(CONFIG, encoding="utf-8").read()):
            if os.path.isdir(match.group(1)):
                roots.append(match.group(1))
    return roots or [REPO]


def module_of(path):
    probe = os.path.dirname(path)
    while len(probe) > 3:
        if os.path.exists(os.path.join(probe, "__manifest__.py")):
            return os.path.basename(probe)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return None


def build():
    widgets = {}
    for root in odoo_roots() + [REPO]:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in {"node_modules", "__pycache__", "tests",
                                    "lib", ".git"} | ENTERPRISE_DIRS]
            for name in files:
                if not name.endswith(".js"):
                    continue
                path = os.path.join(folder, name)
                try:
                    text = io.open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if "registry.category" not in text:
                    continue
                module = module_of(path)
                if not module:
                    continue
                for match in ADD.finditer(text):
                    kind, widget = match.group(1), match.group(2)
                    # The types are declared on the descriptor object, which
                    # is usually the const defined just above the .add call.
                    window = text[max(0, match.start() - 2500):match.start()]
                    types = []
                    found = SUPPORTED.findall(window)
                    if found:
                        types = re.findall(r'["\']([\w]+)["\']', found[-1])
                    current = widgets.setdefault(
                        widget, {"module": module, "kind": kind, "types": types})
                    # A widget defined in web and extended elsewhere belongs to
                    # web: the earliest, most basic module is the safe answer.
                    if module == "web":
                        current["module"] = "web"
                    if types and not current["types"]:
                        current["types"] = types
    with io.open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(widgets, fh, ensure_ascii=False)
    return widgets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    widgets = build()
    if args.json:
        print(json.dumps(widgets, ensure_ascii=False))
        return
    by_module = {}
    for name, info in widgets.items():
        by_module.setdefault(info["module"], []).append(name)
    print("%d widgets from %d modules" % (len(widgets), len(by_module)))
    for module in sorted(by_module, key=lambda m: -len(by_module[m]))[:10]:
        print("  %-24s %3d" % (module, len(by_module[module])))
    typed = [n for n, i in widgets.items() if i["types"]]
    print("with declared field types: %d" % len(typed))
    print("\nweb (always available):")
    print("  " + ", ".join(sorted(by_module.get("web", []))[:30]))


if __name__ == "__main__":
    sys.exit(main())
