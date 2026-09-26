# -*- coding: utf-8 -*-
"""Set this kit up in whatever project it has been dropped into.

Drop the `odoo-devkit` folder at the root of any Odoo project and run:

    python odoo-devkit/install.py --odoo /path/to/odoo/source

It finds the project, finds the editors you have, and writes the paths in
itself. Nothing in the kit contains a path to any particular machine, which
is the point: the same folder works in the next project and on somebody
else's computer.

What it installs
----------------

* `odools.toml`  — the Odoo language server's config, pointing at your source
* `jsconfig.json` — so OWL imports resolve and the frontend is type-checked
* `.vscode/`      — settings, tasks, the XML schema and the snippets
* the xpath / widget / OWL extension, into every editor it finds
* the indexes it all reads

It never overwrites a file you already have without saying so: pass
`--force` to replace, otherwise existing files are left and reported.
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(KIT)
ASSETS = os.path.join(KIT, "assets")

# Where each editor keeps unpacked extensions. All of them are VS Code forks
# and all of them scan the same way, so one copy per directory is enough.
EDITOR_DIRS = [
    (".vscode", "VS Code"),
    (".vscode-insiders", "VS Code Insiders"),
    (".antigravity-ide", "Antigravity"),
    (".cursor", "Cursor"),
    (".windsurf", "Windsurf"),
    (".vscode-oss", "VSCodium"),
]
EXTENSION_ID = "local.odoo-xpath-0.0.1"

# The machine-wide copy, and the one setting worth remembering across
# projects: where the Odoo source is. Everything else is derived per project.
HOME_KIT = os.path.join(os.path.expanduser("~"), ".odoo-devkit")
HOME_CONFIG = os.path.join(HOME_KIT, "config.json")
# Directories on the Windows user PATH that a launcher can be dropped into.
LAUNCHER_DIRS = [
    os.path.join(os.path.expanduser("~"), ".local", "bin"),
    os.path.join(os.path.expanduser("~"), "bin"),
]

LAUNCHER_CMD = """@echo off
REM odoo-devkit — set the kit up in whatever folder you are standing in.
REM Written by install.py --global. The canonical copy lives in %USERPROFILE%\\.odoo-devkit.
setlocal
set KIT=%USERPROFILE%\\.odoo-devkit
if not exist "%KIT%\\install.py" (
  echo The kit is not installed for this user. Run: python install.py --global
  exit /b 1
)
if not exist "odoo-devkit" (
  echo Copying the kit into %CD% ...
  robocopy "%KIT%" "%CD%\\odoo-devkit" /E /NFL /NDL /NJH /NJS /NP /XF config.json >nul
)
python "%CD%\\odoo-devkit\\install.py" %*
"""

LAUNCHER_SH = """#!/bin/sh
# odoo-devkit — set the kit up in whatever folder you are standing in.
KIT="$HOME/.odoo-devkit"
if [ ! -f "$KIT/install.py" ]; then
  echo "The kit is not installed for this user. Run: python install.py --global"
  exit 1
fi
if [ ! -d "odoo-devkit" ]; then
  echo "Copying the kit into $PWD ..."
  cp -r "$KIT" odoo-devkit
  rm -f odoo-devkit/config.json
fi
exec python "$PWD/odoo-devkit/install.py" "$@"
"""


def remembered_odoo():
    try:
        with io.open(HOME_CONFIG, encoding="utf-8") as fh:
            return json.load(fh).get("odoo_path")
    except (OSError, ValueError):
        return None


def remember_odoo(path):
    os.makedirs(HOME_KIT, exist_ok=True)
    data = {}
    try:
        with io.open(HOME_CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        pass
    data["odoo_path"] = posix(path)
    with io.open(HOME_CONFIG, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)


def install_globally():
    """Copy the kit to the home directory and put a launcher on PATH."""
    if os.path.abspath(KIT) != os.path.abspath(HOME_KIT):
        if os.path.isdir(HOME_KIT):
            # Keep config.json: it holds the remembered Odoo path.
            for name in os.listdir(HOME_KIT):
                if name == "config.json":
                    continue
                target = os.path.join(HOME_KIT, name)
                shutil.rmtree(target, ignore_errors=True) \
                    if os.path.isdir(target) else os.remove(target)
        os.makedirs(HOME_KIT, exist_ok=True)
        for name in os.listdir(KIT):
            if name.startswith("."):
                continue  # the built indexes are per project
            source = os.path.join(KIT, name)
            target = os.path.join(HOME_KIT, name)
            if os.path.isdir(source):
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        say("kit copied to %s" % HOME_KIT)

    # Create the first one rather than skipping: on a fresh account
    # ~/.local/bin often does not exist yet, and skipping leaves the command
    # uninstalled with only a line of output to say so.
    if not any(os.path.isdir(folder) for folder in LAUNCHER_DIRS):
        os.makedirs(LAUNCHER_DIRS[0], exist_ok=True)
        say("created %s" % LAUNCHER_DIRS[0])

    placed = []
    for folder in LAUNCHER_DIRS:
        if not os.path.isdir(folder):
            continue
        cmd = os.path.join(folder, "odoo-devkit.cmd")
        with io.open(cmd, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(LAUNCHER_CMD)
        sh = os.path.join(folder, "odoo-devkit")
        with io.open(sh, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(LAUNCHER_SH)
        try:
            os.chmod(sh, 0o755)
        except OSError:
            pass
        placed.append(folder)
    if placed:
        say("launcher installed in: %s" % ", ".join(placed))
        # Being on PATH is what makes it a command. A launcher in a directory
        # the shell does not search is a file.
        path_entries = [os.path.normcase(os.path.normpath(p))
                        for p in os.environ.get("PATH", "").split(os.pathsep) if p]
        on_path = [f for f in placed
                   if os.path.normcase(os.path.normpath(f)) in path_entries]
        if on_path:
            say("from now on, in any project folder: odoo-devkit")
        else:
            say("NOTE: %s is not on PATH, so `odoo-devkit` will not be found."
                % placed[0])
            say("Add it: setx PATH \"%%PATH%%;%s\"  (then open a new terminal)"
                % placed[0])
    else:
        say("no directory on PATH to put the launcher in — looked in %s"
            % ", ".join(LAUNCHER_DIRS))
    return placed


def say(message):
    print("  " + message)


# ── finding things ───────────────────────────────────────────────────

def looks_like_odoo(path):
    """An Odoo source tree has odoo/release.py and an addons directory."""
    return (os.path.exists(os.path.join(path, "odoo", "release.py"))
            and os.path.isdir(os.path.join(path, "addons")))


def odoo_version(path):
    try:
        text = io.open(os.path.join(path, "odoo", "release.py"),
                       encoding="utf-8").read()
        match = re.search(r"version_info\s*=\s*\(\s*(\d+)\s*,\s*(\d+)", text)
        return "%s.%s" % match.groups() if match else "?"
    except OSError:
        return "?"


def find_odoo(hint):
    if hint:
        hint = os.path.abspath(hint)
        if looks_like_odoo(hint):
            return hint
        # A parent or a single child may be the real root.
        for candidate in [os.path.dirname(hint)] + [
                os.path.join(hint, name) for name in
                (os.listdir(hint) if os.path.isdir(hint) else [])]:
            if os.path.isdir(candidate) and looks_like_odoo(candidate):
                return candidate
        return None

    # Nothing given: this project's own config, then what was remembered
    # the last time the kit was set up anywhere, then a look around.
    config = os.path.join(PROJECT, "odools.toml")
    if os.path.exists(config):
        for match in re.finditer(r'"([^"]+)"',
                                 io.open(config, encoding="utf-8").read()):
            if looks_like_odoo(match.group(1)):
                return match.group(1)

    saved = remembered_odoo()
    if saved and looks_like_odoo(saved):
        return saved

    roots = [os.path.dirname(PROJECT), os.path.dirname(os.path.dirname(PROJECT))]
    seen = set()
    for root in roots:
        if not os.path.isdir(root) or root in seen:
            continue
        seen.add(root)
        for name in sorted(os.listdir(root)):
            candidate = os.path.join(root, name)
            if not os.path.isdir(candidate):
                continue
            if looks_like_odoo(candidate):
                return candidate
            # One level deeper: unpacked archives nest a folder of the same
            # name inside themselves.
            try:
                children = os.listdir(candidate)
            except OSError:
                continue
            for child in children:
                deeper = os.path.join(candidate, child)
                if os.path.isdir(deeper) and looks_like_odoo(deeper):
                    return deeper
    return None


def addon_dirs():
    """Every directory under the project that holds modules."""
    found = []
    for folder, dirs, _files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in
                   {"node_modules", "__pycache__", "odoo-devkit"}]
        if any(os.path.exists(os.path.join(folder, d, "__manifest__.py"))
               for d in dirs):
            found.append(folder)
            dirs[:] = []  # modules do not nest
    return found or [PROJECT]


def modules_with_frontend():
    out = []
    for folder, dirs, _files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in {"node_modules", "__pycache__"}]
        if os.path.exists(os.path.join(folder, "__manifest__.py")) and \
                os.path.isdir(os.path.join(folder, "static", "src")):
            out.append(os.path.relpath(folder, PROJECT).replace("\\", "/"))
            dirs[:] = []
    return out


def posix(path):
    return os.path.abspath(path).replace("\\", "/")


# ── writing ──────────────────────────────────────────────────────────

def write(relative, content, force, note=""):
    target = os.path.join(PROJECT, relative)
    if os.path.exists(target) and not force:
        say("kept %s (exists — --force to replace)" % relative)
        return False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    say("wrote %s%s" % (relative, note))
    return True


def odools(odoo, addons):
    lines = [
        "# Odoo language server (extension Odoo.odoo).",
        "#",
        "# Written by odoo-devkit/install.py. Both paths below matter:",
        "# odoo_path gives the server odoo/addons — base and web — and the",
        "# separate top-level addons directory holds everything a module",
        "# really depends on: mail, contacts, portal, account. Without it",
        "# every manifest reports 'depends on mail which is not found'.",
        "",
        "[[config]]",
        'name = "default"',
        'odoo_path = "%s"' % posix(odoo),
        "addons_paths = [",
        '    "%s",' % posix(os.path.join(odoo, "addons")),
    ]
    for path in addons:
        lines.append('    "%s",' % posix(path))
    lines += ["]", 'python_path = "%s"' % posix(sys.executable), ""]
    return "\n".join(lines)


def jsconfig(odoo, frontend_modules):
    web = posix(os.path.join(odoo, "addons", "web", "static", "src"))
    paths = {
        "@odoo/owl": ["odoo-devkit/jstypes/node_modules/@odoo/owl/dist/types/owl.d.ts"],
        # NOT .../dist/types/* — Odoo's own @types/owl.d.ts declares the
        # module as `export * from "@odoo/owl/dist/types/owl"`, and an
        # ambient declaration beats a path mapping. With the star pointing
        # inside dist/types, that re-export resolved to
        # dist/types/dist/types/owl, which does not exist, so the module
        # came back with no exports at all: "has no exported member
        # 'Component'" on an import that is perfectly correct.
        "@odoo/owl/*": ["odoo-devkit/jstypes/node_modules/@odoo/owl/*"],
    }
    for addon in ("web", "mail", "portal", "account"):
        source = os.path.join(odoo, "addons", addon, "static", "src")
        if os.path.isdir(source):
            paths["@%s/*" % addon] = [posix(source) + "/*"]
    for module in frontend_modules:
        paths["@%s/*" % os.path.basename(module)] = ["%s/static/src/*" % module]

    data = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "ESNext",
            "moduleResolution": "bundler",
            "baseUrl": ".",
            "allowJs": True,
            "checkJs": True,
            "strict": False,
            "noImplicitAny": False,
            "skipLibCheck": True,
            "lib": ["ES2022", "DOM", "DOM.Iterable"],
            "paths": paths,
        },
        "include": ["*/static/src/**/*.js", "**/static/src/**/*.js",
                    "odoo-devkit/jstypes/*.d.ts"],
        "exclude": ["**/node_modules", "**/static/lib/**",
                    "**/static/**/*.min.js", "**/__pycache__"],
    }
    header = (
        "// Written by odoo-devkit/install.py.\n"
        "//\n"
        "// Odoo ships .d.ts files for its frontend and OWL publishes its own\n"
        "// types, but none of it is used until something maps the import\n"
        "// names onto those files: `@web/core/registry` is an Odoo module id,\n"
        "// not a path that resolves on disk. That is what `paths` is.\n"
        "//\n"
        "// Re-run the installer after adding a module with static/src.\n")
    return header + json.dumps(data, indent=2) + "\n"


def odoo_globals(odoo):
    types = os.path.join(odoo, "addons", "web", "static", "src", "@types")
    lines = [
        "// Odoo ships TypeScript declarations for its frontend, in",
        "// addons/web/static/src/@types. Nothing imports them, so they are",
        "// referenced here and this file is what jsconfig includes.",
        "//",
        "// Written by odoo-devkit/install.py.",
        "",
    ]
    if os.path.isdir(types):
        for name in sorted(os.listdir(types)):
            if name.endswith(".d.ts"):
                lines.append('/// <reference path="%s" />'
                             % posix(os.path.join(types, name)))
        registries = os.path.join(types, "registries")
        if os.path.isdir(registries):
            for name in sorted(os.listdir(registries)):
                if name.endswith(".d.ts"):
                    lines.append('/// <reference path="%s" />'
                                 % posix(os.path.join(registries, name)))
    return "\n".join(lines) + "\n"


VSCODE_SETTINGS = """{
  // Written by odoo-devkit/install.py.
  //
  // The one that matters most: by default the editor pads every completion
  // list with words scraped out of open files, which arrive with the same
  // icon as the real ones and bury them.
  "editor.wordBasedSuggestions": "off",
  "editor.suggest.showWords": false,
  "editor.snippetSuggestions": "bottom",
  "editor.quickSuggestions": { "other": true, "comments": false, "strings": true },

  // The interpreter, pinned. Without it the editor picks whichever Python it
  // finds first, and one without psycopg2 and werkzeug makes Pylance unable to
  // resolve `from odoo import models` — which is the whole of Python
  // completion in an Odoo module.
  "python.defaultInterpreterPath": "%(python_exe)s",

  "python.analysis.extraPaths": [%(python_paths)s],
  "python.analysis.packageIndexDepth": 2,
  "python.analysis.autoImportCompletions": false,
  "python.analysis.typeCheckingMode": "off",
  "python.analysis.diagnosticMode": "openFilesOnly",

  "files.exclude": { "**/__pycache__": true, "**/*.pyc": true },
  "search.exclude": { "**/__pycache__": true, "**/static/lib": true },

  // Odoo publishes no XML schema, so <record> completes nothing anywhere and
  // a missing model= is found at install. This one is ours, and is
  // deliberately permissive: unknown attributes pass, and the inside of a
  // view's arch is not checked at all.
  "xml.fileAssociations": [
    { "pattern": "**/views/*.xml", "systemId": "./.vscode/odoo.xsd" },
    { "pattern": "**/data/*.xml", "systemId": "./.vscode/odoo.xsd" },
    { "pattern": "**/security/*.xml", "systemId": "./.vscode/odoo.xsd" },
    { "pattern": "**/report/*.xml", "systemId": "./.vscode/odoo.xsd" },
    { "pattern": "**/wizard/*.xml", "systemId": "./.vscode/odoo.xsd" }
  ],
  "xml.validation.schema.enabled": "always",

  // This one defaults to ./addons — a folder most Odoo projects do not have,
  // because the modules sit at the root. Left wrong it finds nothing and its
  // output says so, which is easy to read as the language server failing.
  "odooImport.addonDirectories": [%(addon_dirs)s],

  "Odoo.serverConfigPath": "%(odools)s",
  "Odoo.selectedProfile": "default",
  "Odoo.serverLogLevel": "warn",

  "[python]": { "editor.rulers": [79] },
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "files.eol": "\\n"
}
"""

VSCODE_TASKS = """{
  // Written by odoo-devkit/install.py.
  "version": "2.0.0",
  "tasks": [
    {
      // Ctrl+Shift+B. Prints every xpath that would actually resolve against
      // the views this file inherits.
      "label": "Odoo: xpath anchors for this file",
      "type": "shell",
      "command": "python",
      "args": ["odoo-devkit/xpath_anchors.py", "${relativeFile}"],
      "group": { "kind": "build", "isDefault": true },
      "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
      "problemMatcher": []
    },
    {
      "label": "Odoo: xpath anchors for a view id",
      "type": "shell",
      "command": "python",
      "args": ["odoo-devkit/xpath_anchors.py", "${input:viewId}", "--tree"],
      "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
      "problemMatcher": []
    },
    {
      // What Odoo 19 removed, before a build finds it. Zero is the good
      // answer; everything it reports cost somebody a push once.
      "label": "Odoo: check for what 19 removed",
      "type": "shell",
      "command": "python",
      "args": ["odoo-devkit/odoo19_check.py"],
      "presentation": { "reveal": "always", "panel": "dedicated", "clear": true },
      "problemMatcher": {
        "owner": "odoo",
        "fileLocation": ["relative", "${workspaceFolder}"],
        "pattern": {
          "regexp": "^(.*):(\\\\d+): (.*)$",
          "file": 1, "line": 2, "message": 3
        }
      }
    },
    {
      "label": "Odoo: rebuild the devkit indexes",
      "type": "shell",
      "command": "python",
      "args": ["odoo-devkit/install.py", "--indexes-only"],
      "presentation": { "reveal": "always", "panel": "dedicated" },
      "problemMatcher": []
    }
  ],
  "inputs": [
    {
      "id": "viewId",
      "type": "promptString",
      "description": "View external id, e.g. base.view_partner_form",
      "default": "base.view_partner_form"
    }
  ]
}
"""


# ── steps ────────────────────────────────────────────────────────────

def install_extension():
    source = os.path.join(KIT, "extension")
    home = os.path.expanduser("~")
    installed = []
    for folder, label in EDITOR_DIRS:
        base = os.path.join(home, folder, "extensions")
        if not os.path.isdir(base):
            continue
        target = os.path.join(base, EXTENSION_ID)
        shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target, exist_ok=True)
        for name in ("package.json", "extension.js"):
            shutil.copy2(os.path.join(source, name), target)
        installed.append(label)
    return installed


def npm_types(skip):
    """OWL's own types, and three's if the project uses three."""
    target = os.path.join(KIT, "jstypes")
    if skip:
        say("skipped npm (--no-npm)")
        return
    if os.path.exists(os.path.join(target, "node_modules", "@odoo", "owl")):
        say("owl types already present")
        return
    if not shutil.which("npm"):
        say("npm not found — OWL types skipped, everything else still works")
        return
    os.makedirs(target, exist_ok=True)
    if not os.path.exists(os.path.join(target, "package.json")):
        subprocess.run(["npm", "init", "-y"], cwd=target, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say("installing owl types (npm)…")
    subprocess.run(["npm", "install", "--silent", "@odoo/owl", "typescript"],
                   cwd=target, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say("owl types installed")


def last_lines(raw, count):
    """The tail of a subprocess's stderr, or a line saying there was none."""
    text = (raw or b"").decode("utf-8", errors="replace").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-count:] or ["(no output)"]


def ensure_lxml():
    """The kit's one dependency. Without it the view index never builds, and
    nothing about that is obvious from the outside: the extension logs a
    failure to a channel nobody has open."""
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        pass
    say("lxml is missing — installing it")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "lxml"],
        check=False)
    try:
        import lxml  # noqa: F401,F811
        say("lxml installed")
        return True
    except ImportError:
        say("could not install lxml (pip exited %s)." % result.returncode)
        say("Install it by hand: %s -m pip install lxml" % sys.executable)
        return False


def build_indexes():
    if not ensure_lxml():
        say("indexes skipped: nothing can be parsed without lxml")
        return False

    ok = True
    for script in ("owl_index.py", "widget_index.py"):
        result = subprocess.run([sys.executable, os.path.join(KIT, script)],
                                cwd=PROJECT, check=False,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        label = script.replace("_index.py", " index")
        if result.returncode:
            ok = False
            say("FAILED to build %s:" % label)
            for line in last_lines(result.stderr, 2):
                say("  " + line)
        else:
            say("built %s" % label)

    result = subprocess.run(
        [sys.executable, os.path.join(KIT, "xpath_anchors.py"),
         "base.view_partner_form", "--json", "--rebuild"],
        cwd=PROJECT, check=False, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)
    if result.returncode:
        ok = False
        say("FAILED to build xpath index:")
        for line in last_lines(result.stderr, 3):
            say("  " + line)
    else:
        say("built xpath index")
    return ok


INDEX_FILES = (".xpath_anchors_cache.json", ".widget_index.json",
               ".owl_index.json")


def packed_indexes():
    """The indexes that came with the kit, if it was packed with any."""
    return [name for name in INDEX_FILES
            if os.path.exists(os.path.join(KIT, name))]


def pack(destination):
    """Copy the kit, indexes included, ready to zip and carry.

    The point is a target machine that has no Odoo source and no Python:
    the extension reads these files and nothing else, so core completions
    work the moment it is dropped in.
    """
    destination = os.path.abspath(destination)
    target = (destination if os.path.basename(destination) == "odoo-devkit"
              else os.path.join(destination, "odoo-devkit"))
    if os.path.abspath(target) == os.path.abspath(KIT):
        say("pack destination is the kit itself")
        return False

    missing = [n for n in INDEX_FILES if not os.path.exists(os.path.join(KIT, n))]
    if missing:
        say("no indexes to pack yet — run the installer here first")
        return False

    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(KIT, target)
    # config.json is this user's remembered Odoo path; it means nothing on
    # another machine and would send the installer looking at a path that
    # does not exist.
    for junk in ("config.json",):
        path = os.path.join(target, junk)
        if os.path.exists(path):
            os.remove(path)

    size = sum(os.path.getsize(os.path.join(folder, name))
               for folder, _dirs, files in os.walk(target)
               for name in files)
    say("packed to %s (%.0f MB, indexes included)" % (target, size / 1e6))
    say("On the other machine: drop it in a project and run")
    say("  python odoo-devkit/install.py        (or without Python, just")
    say("  copy .vscode/ and the extension by hand — see the README)")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odoo", help="path to the Odoo source tree")
    parser.add_argument("--force", action="store_true",
                        help="replace files that already exist")
    parser.add_argument("--no-npm", action="store_true")
    parser.add_argument("--indexes-only", action="store_true")
    parser.add_argument("--pack", metavar="DEST",
                        help="copy the kit, indexes included, ready to carry "
                             "to a machine with no Odoo source")
    parser.add_argument("--global", dest="make_global", action="store_true",
                        help="also install a machine-wide copy and put an "
                             "`odoo-devkit` command on PATH")
    args = parser.parse_args()

    print("odoo-devkit")
    print("project: %s" % PROJECT)

    if args.pack:
        return 0 if pack(args.pack) else 1

    if args.indexes_only:
        build_indexes()
        return 0

    odoo = find_odoo(args.odoo)
    if not odoo:
        packed = packed_indexes()
        if len(packed) == len(INDEX_FILES):
            # The kit was packed with its indexes. Everything that reads them
            # works; only this project's own modules are missing from them.
            print("\nNo Odoo source here — using the indexes this kit was")
            print("packed with. Core completions work; your own modules are")
            print("not in them until you re-run with --odoo.")
            install_extension()
            print("\nDone. Reload the editor window.")
            return 0
        print("\nCould not find an Odoo source tree.")
        print("Pass it: python odoo-devkit/install.py --odoo C:/path/to/odoo")
        print("It is the folder that holds both odoo/release.py and addons/.")
        return 1
    print("odoo:    %s  (version %s)" % (odoo, odoo_version(odoo)))
    remember_odoo(odoo)

    addons = addon_dirs()
    frontend = modules_with_frontend()
    print("addons:  %s" % ", ".join(os.path.relpath(a, PROJECT) or "." for a in addons))
    print("frontend modules: %s" % (", ".join(frontend) or "none"))
    print("")

    write("odools.toml", odools(odoo, addons), True)
    write("jsconfig.json", jsconfig(odoo, frontend), args.force)
    write("odoo-devkit/jstypes/odoo-globals.d.ts", odoo_globals(odoo), True)
    write(".vscode/settings.json",
          VSCODE_SETTINGS % {
              "python_paths": '\n    "%s",\n    "."\n  ' % posix(odoo),
              "python_exe": posix(sys.executable),
              "odools": posix(os.path.join(PROJECT, "odools.toml")),
              "addon_dirs": ", ".join(
                  '"."' if os.path.relpath(a, PROJECT) == "."
                  else '"./%s"' % os.path.relpath(a, PROJECT).replace("\\", "/")
                  for a in addons),
          }, args.force)
    write(".vscode/tasks.json", VSCODE_TASKS, args.force)

    for name in ("odoo.xsd", "odoo.code-snippets"):
        source = os.path.join(ASSETS, name)
        if os.path.exists(source):
            write(os.path.join(".vscode", name),
                  io.open(source, encoding="utf-8").read(), True)

    editors = install_extension()
    say("extension installed into: %s" % (", ".join(editors) or "no editor found"))

    npm_types(args.no_npm)
    build_indexes()

    if args.make_global:
        install_globally()

    print("\nDone. Reload the editor window.")
    if not editors:
        print("No editor extension directory was found — the tasks and the")
        print("scripts still work from the terminal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
