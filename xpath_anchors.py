# -*- coding: utf-8 -*-
"""What can I hang an xpath on, in the view I am inheriting?

The commonest failure when extending a view is an `expr` that points at a node
the parent does not have. It fails at install with

    Element '<xpath expr="//x">' cannot be located in parent view

and does not say what the parent *does* contain — so the loop is guess, push,
wait for the build, read the same message again.

This reads the parent view and prints every anchor it really has, ready to
paste. It searches this repo and the local Odoo source, so it answers for core
views too.

    python tools/xpath_anchors.py base.view_partner_form
    python tools/xpath_anchors.py village_base.view_unit_form --tree

Given a file instead of an id, it answers for every inherit_id in that file:

    python tools/xpath_anchors.py village_charges/views/village_views.xml

It reads the parent's OWN arch. Other modules' additions to the same view are
listed at the end, because a node added by another module is a legal anchor
only when your module depends on that one.
"""
import argparse
import io
import json
import os
import re
import sys
import time

from lxml import etree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Read from the language server's own config, so there is one place holding
# the path to the Odoo source rather than two that can disagree.
CONFIG = os.path.join(REPO, "odools.toml")

# Attributes that make a node addressable, best first. `name` is stable;
# a class is stable enough; a position index is not, and is offered last.
NAMED = ("name", "id", "string", "t-name")


def odoo_paths():
    paths = []
    if os.path.exists(CONFIG):
        text = open(CONFIG, encoding="utf-8").read()
        for match in re.finditer(r'"([^"]+)"', text):
            path = match.group(1)
            if os.path.isdir(path):
                paths.append(path)
    return paths or [REPO]


# The local Odoo source has an `ent_addons` directory inside it holding the
# Enterprise modules — helpdesk, industry_fsm, documents — and a second copy
# of base. Skipped by default, and for more than tidiness: the village line is
# Community only (RULE #10c), and a tool that cheerfully offers an anchor from
# an Enterprise view is a tool that helps you write a module which installs
# here and fails on the customer's server. --enterprise includes them, marked.
ENTERPRISE_DIRS = {"ent_addons", "enterprise", "odoo-enterprise"}


# The kinds worth completing, and what asks for each.
#   menu    → a menuitem's parent=
#   action  → a menuitem's action=
#   group   → groups= anywhere
ACTION_MODELS = ("ir.actions.act_window", "ir.actions.server",
                 "ir.actions.client", "ir.actions.report", "ir.actions.act_url")


MODEL_DIRS = {"models", "model", "wizard", "wizards"}


FIELD_RE = re.compile(r'^    ([a-z]\w*)\s*=\s*fields\.(\w+)\(', re.M)
STRING_RE = re.compile(r'string\s*=\s*["\']([^"\']{0,60})["\']')
# Core writes the comodel both ways — positionally in the older files, and as
# comodel_name= in the newer ones like sale_order.py. Match both, or two
# thirds of sale.order's relations come back with no target.
COMODEL_RE = re.compile(
    r'\(\s*["\']([\w.]+)["\']|comodel_name\s*=\s*["\']([\w.]+)["\']')
CLASS_RE = re.compile(r'^class\s+\w+\(', re.M)
NAME_RE = re.compile(r'^    _name\s*=\s*["\']([\w.]+)["\']', re.M)
# The whole right-hand side, because _inherit is often a list and every
# entry matters: `_inherit = ["mail.thread", "mail.activity.mixin"]` brings
# the fields of both.
INHERIT_RE = re.compile(r'^    _inherit\s*=\s*(\[[^\]]*\]|["\'][\w.]+["\'])', re.M)
QUOTED_RE = re.compile(r'["\']([\w.]+)["\']')
# Delegation: the child reads every field of the parent through the column
# named as the value. The keys are the models that matter here.
INHERITS_RE = re.compile(r'^    _inherits\s*=\s*(\{[^}]*\})', re.M)
KEY_RE = re.compile(r'["\']([\w.]+)["\']\s*:')
RELATIONAL = {"Many2one", "One2many", "Many2many"}


def class_bodies(text):
    """Each class in the file, as a slice. Cheap: anchors, then slicing."""
    starts = [m.start() for m in CLASS_RE.finditer(text)]
    for index, begin in enumerate(starts):
        finish = starts[index + 1] if index + 1 < len(starts) else len(text)
        yield text[begin:finish]


def index_models(roots, ids, skip, model_fields=None, model_parents=None):
    """The ir.model ids Odoo generates: village.unit -> model_village_unit.

    They exist only in the database, so there is nothing to copy them from
    and they are retyped from memory into every ACL line.
    """
    pattern = re.compile(r'^\s*_name\s*=\s*["\']([\w.]+)["\']', re.M)
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            module = None
            probe = folder
            while len(probe) > len(root):
                if os.path.exists(os.path.join(probe, "__manifest__.py")):
                    module = os.path.basename(probe)
                    break
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
            if not module:
                continue
            # Only the folders models actually live in. Reading every .py in
            # Odoo took eighty seconds; this takes three, and a model defined
            # outside these four is rare enough to look up by hand.
            # Anywhere under a models/wizard folder, not only directly in
            # one: mail keeps discuss.channel in models/discuss/, and
            # matching on the basename alone missed the whole subtree —
            # twenty-five fields of a real model reported as missing.
            if not (MODEL_DIRS & set(folder.replace("/", os.sep).split(os.sep))):
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                try:
                    text = io.open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                # `_inherit` as well as `_name`: a file that only extends a
                # model has no _name at all, and skipping those loses every
                # field one addon adds to another's model — which is most of
                # what account, sale and purchase do to each other.
                if "_name" not in text and "_inherit" not in text:
                    continue
                for match in pattern.finditer(text):
                    model = match.group(1)
                    ids.setdefault("%s.model_%s" % (module, model.replace(".", "_")), {
                        "kind": "model",
                        "model": "ir.model",
                        "name": model,
                        "module": module,
                    })

                if model_fields is None:
                    continue
                if model_parents is None:
                    model_parents = {}
                # Per class, because one file holds several models and a
                # field belongs to the class it is written in. A class with
                # only _inherit adds to the model it names — which is how
                # account, sale and purchase all put fields on res.partner.
                for body in class_bodies(text):
                    named = NAME_RE.search(body)
                    inherited = INHERIT_RE.search(body)
                    parents = (QUOTED_RE.findall(inherited.group(1))
                               if inherited else [])
                    delegated = INHERITS_RE.search(body)
                    if delegated:
                        parents = parents + KEY_RE.findall(delegated.group(1))
                    if named:
                        # A model of its own: everything in _inherit is a
                        # mixin it takes fields from.
                        target, mixins = named.group(1), parents
                    elif parents:
                        # No _name: this class adds to the first model named,
                        # and any others are mixins mixed into it.
                        target, mixins = parents[0], parents[1:]
                    else:
                        continue
                    if mixins:
                        known = model_parents.setdefault(target, [])
                        for parent in mixins:
                            if parent != target and parent not in known:
                                known.append(parent)
                    bucket = model_fields.setdefault(target, {})
                    for field in FIELD_RE.finditer(body):
                        fname, ftype = field.groups()
                        if fname in bucket:
                            continue
                        # The arguments, as a window rather than a match:
                        # a lazy pattern here is what made this slow.
                        args = body[field.end():field.end() + 300]
                        label = STRING_RE.search(args)
                        comodel = (COMODEL_RE.search(body[field.end() - 1:
                                                         field.end() + 90])
                                   if ftype in RELATIONAL else None)
                        bucket[fname] = [
                            ftype,
                            label.group(1) if label else "",
                            (comodel.group(1) or comodel.group(2))
                            if comodel else "",
                        ]


def index_views(roots, with_enterprise=False, ids=None):
    """Every ir.ui.view and template in the tree, by external id.

    `ids` collects the other things an XML file points at by name — menus,
    actions and groups — in the same walk, because walking six thousand
    files twice to answer two questions would be silly.
    """
    views = {}
    skip = {".git", "node_modules", "__pycache__", "lib", "tests", "i18n"}
    if not with_enterprise:
        skip |= ENTERPRISE_DIRS
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            if os.sep + "static" + os.sep in folder + os.sep:
                continue
            module = None
            probe = folder
            while probe.startswith(tuple(roots)) and len(probe) > len(root):
                if os.path.exists(os.path.join(probe, "__manifest__.py")):
                    module = os.path.basename(probe)
                    break
                probe = os.path.dirname(probe)
            if not module:
                continue
            for name in files:
                if not name.endswith(".xml"):
                    continue
                path = os.path.join(folder, name)
                try:
                    tree = etree.parse(path)
                except etree.XMLSyntaxError:
                    continue
                for rec in tree.getroot().iter("record"):
                    if ids is not None and rec.get("id") and "." not in rec.get("id"):
                        model = rec.get("model") or ""
                        kind = ("action" if model in ACTION_MODELS
                                else "group" if model == "res.groups"
                                else None)
                        if kind:
                            ids["%s.%s" % (module, rec.get("id"))] = {
                                "kind": kind,
                                "model": model,
                                "name": (rec.findtext("field[@name='name']")
                                         or "").strip()[:80],
                                "module": module,
                            }
                    if rec.get("model") != "ir.ui.view" or not rec.get("id"):
                        continue
                    arch = rec.find("field[@name='arch']")
                    inherit = rec.find("field[@name='inherit_id']")
                    views["%s.%s" % (module, rec.get("id"))] = {
                        "enterprise": any(
                            part in ENTERPRISE_DIRS for part in path.split(os.sep)),
                        "path": path,
                        "arch": arch,
                        "inherit": inherit is not None and inherit.get("ref"),
                        "model": (rec.findtext("field[@name='model']") or "").strip(),
                    }
                if ids is not None:
                    for menu in tree.getroot().iter("menuitem"):
                        if menu.get("id") and "." not in menu.get("id"):
                            ids["%s.%s" % (module, menu.get("id"))] = {
                                "kind": "menu",
                                "model": "ir.ui.menu",
                                "name": (menu.get("name") or "").strip()[:80],
                                "module": module,
                                "parent": menu.get("parent") or "",
                            }

                for tpl in tree.getroot().iter("template"):
                    if tpl.get("id"):
                        views["%s.%s" % (module, tpl.get("id"))] = {
                            "enterprise": any(
                                part in ENTERPRISE_DIRS
                                for part in path.split(os.sep)),
                            "path": path, "arch": tpl,
                            "inherit": tpl.get("inherit_id"), "model": "qweb",
                        }
    return views


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".xpath_anchors_cache.json")


def repo_mtime():
    """Newest XML in this repo. Core is assumed not to move under us."""
    newest = 0.0
    for folder, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs
                   if d not in {".git", "node_modules", "__pycache__", "i18n"}]
        for name in files:
            if name.endswith(".xml"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(folder, name)))
                except OSError:
                    pass
    return newest


def build_cache(roots, with_enterprise=False):
    """Index once (about three seconds) so every later lookup is instant."""
    ids = {}
    views = index_views(roots, with_enterprise, ids)
    skip = {"node_modules", "__pycache__", ".git", "tests", "static"}
    if not with_enterprise:
        skip |= ENTERPRISE_DIRS
    model_fields, model_parents = {}, {}
    index_models(roots, ids, skip, model_fields, model_parents)
    data = {"built": time.time(), "repo_mtime": repo_mtime(),
            "enterprise": with_enterprise, "views": {}, "ids": ids,
            "fields": model_fields, "inherits": model_parents}
    for xmlid, view in views.items():
        data["views"][xmlid] = {
            "path": view["path"],
            "model": view["model"],
            "inherit": view["inherit"] or "",
            "enterprise": bool(view.get("enterprise")),
            "anchors": ([list(a) for a in anchors(view["arch"])]
                        if view["arch"] is not None else []),
        }
    with io.open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def load_cache(roots, with_enterprise=False, rebuild=False):
    if not rebuild and os.path.exists(CACHE):
        try:
            data = json.load(io.open(CACHE, encoding="utf-8"))
        except ValueError:
            data = None
        # Core does not change; our own files do, so only those are checked.
        if data and data.get("enterprise") == with_enterprise \
                and data.get("repo_mtime", 0) >= repo_mtime():
            return data
    return build_cache(roots, with_enterprise)


def anchors(arch):
    """Every expression that would resolve against this arch, best first."""
    out, seen = [], set()
    counts = {}
    for node in arch.iter():
        if not isinstance(node.tag, str):
            continue
        counts[node.tag] = counts.get(node.tag, 0) + 1

    for node in arch.iter():
        if not isinstance(node.tag, str) or node is arch:
            continue
        tag = node.tag
        for attr in NAMED:
            value = node.get(attr)
            if value and "\n" not in value and len(value) < 60:
                expr = "//%s[@%s='%s']" % (tag, attr, value)
                if expr not in seen:
                    seen.add(expr)
                    out.append((0, expr, tag))
                break
        else:
            classes = (node.get("class") or "").split()
            if classes:
                expr = "//%s[hasclass('%s')]" % (tag, classes[0])
                if expr not in seen:
                    seen.add(expr)
                    out.append((1, expr, tag))
            elif counts.get(tag) == 1:
                # Unique in the view, so the bare tag is unambiguous.
                expr = "//%s" % tag
                if expr not in seen:
                    seen.add(expr)
                    out.append((2, expr, tag))
    return sorted(out)


def outline(node, depth=0, lines=None):
    lines = [] if lines is None else lines
    if isinstance(node.tag, str):
        label = node.tag
        for attr in NAMED + ("class",):
            if node.get(attr):
                label += " %s=%r" % (attr, node.get(attr))
                break
        lines.append("  " * depth + label)
    for child in node:
        outline(child, depth + 1, lines)
    return lines


def report(xmlid, views, show_tree):
    view = views.get(xmlid)
    if not view:
        near = [k for k in views if xmlid.split(".")[-1] in k][:8]
        print("  not found: %s" % xmlid)
        if near:
            print("  did you mean: %s" % ", ".join(near))
        return
    if view["arch"] is None:
        print("  %s has no arch to anchor on." % xmlid)
        return

    print("\n%s   (%s)" % (xmlid, view["model"] or "?"))
    print("  %s" % os.path.relpath(view["path"], REPO)
          if view["path"].startswith(REPO) else "  " + view["path"])

    if view.get("enterprise"):
        print("  *** ENTERPRISE. Nothing in the village line may inherit this:")
        print("      it installs here and is missing on the customer's server.")

    if view["inherit"]:
        print("  NOTE: this view is itself an extension of %s — anchor on the"
              % view["inherit"])
        print("        original unless you mean to extend the extension.")

    found = anchors(view["arch"])
    if not found:
        print("  nothing addressable.")
    else:
        print("\n  anchors:")
        for rank, expr, tag in found:
            mark = {0: " ", 1: "~", 2: "!"}[rank]
            print("   %s %s" % (mark, expr))
        print("\n   ~ matched by class, ! matched by tag alone (unique today,")
        print("     and no longer unique the day somebody adds a second one)")

    others = [k for k, v in views.items() if v["inherit"] == xmlid]
    if others:
        print("\n  also extended by, whose nodes are anchors only if you")
        print("  depend on them:")
        for other in sorted(others):
            print("    %s" % other)

    if show_tree:
        print("\n  structure:")
        for line in outline(view["arch"])[:200]:
            print("    " + line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="a view xmlid, or an XML file")
    parser.add_argument("--tree", action="store_true",
                        help="also print the parent's structure")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable, for the editor extension")
    parser.add_argument("--rebuild", action="store_true",
                        help="throw the cache away and index again")
    parser.add_argument("--enterprise", action="store_true",
                        help="also search the Enterprise source (village is "
                             "Community only, so this is normally wrong)")
    args = parser.parse_args()

    roots = [REPO] + odoo_paths()
    roots = list(dict.fromkeys(os.path.abspath(p) for p in roots))

    if args.json:
        data = load_cache(roots, args.enterprise, args.rebuild)
        target = args.target
        if target.endswith(".xml"):
            path = target if os.path.isabs(target) else os.path.join(REPO, target)
            refs = []
            try:
                for rec in etree.parse(path).getroot().iter("record"):
                    node = rec.find("field[@name='inherit_id']")
                    if node is not None and node.get("ref"):
                        refs.append(node.get("ref"))
            except (OSError, etree.XMLSyntaxError):
                pass
            out = {ref: data["views"].get(ref, {}) for ref in dict.fromkeys(refs)}
        else:
            out = {target: data["views"].get(target, {})}
        print(json.dumps(out, ensure_ascii=False))
        return

    views = index_views(roots, args.enterprise)
    print("indexed %d views from %d roots" % (len(views), len(roots)))

    if args.target.endswith(".xml"):
        path = args.target if os.path.isabs(args.target) \
            else os.path.join(REPO, args.target)
        tree = etree.parse(path)
        refs = []
        for rec in tree.getroot().iter("record"):
            node = rec.find("field[@name='inherit_id']")
            if node is not None and node.get("ref"):
                refs.append(node.get("ref"))
        if not refs:
            print("no inherit_id in that file.")
            return
        for ref in dict.fromkeys(refs):
            report(ref, views, args.tree)
    else:
        report(args.target, views, args.tree)


if __name__ == "__main__":
    sys.exit(main())
