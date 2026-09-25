# Installing odoo-devkit

Everything here is done by `install.py`. It finds what it can, writes every
path itself, and tells you plainly when it cannot. Nothing in the repository
contains a path to any particular machine — that is what makes the same folder
work on the next computer.

---

## 1. Before you start

| | Check | If missing |
|---|---|---|
| Python 3.8+ | `python --version` | [python.org](https://python.org). You already have it if you run Odoo. |
| `lxml` | `python -c "import lxml"` | The installer installs it. Or `pip install lxml`. |
| An Odoo checkout | see below | Clone it: `git clone https://github.com/odoo/odoo.git -b 19.0` |
| An editor | VS Code, Cursor, Antigravity, Windsurf, VSCodium | Any of them; all are detected. |
| Node + npm | `npm --version` | **Optional.** Only the OWL type definitions need it. |

### What counts as "an Odoo checkout"

The folder that holds **both** of these:

```
<odoo>/odoo/release.py
<odoo>/addons/
```

That is the root you pass. Common shapes:

```
/opt/odoo/odoo                         ← the root
C:\odoo\server                          ← the root
F:\src\odoo-19.0\odoo-19.0              ← unpacked archives nest one level
```

If you point at the wrong level the installer says so rather than guessing.

---

## 2. Install

### The usual way — once per machine

```bash
git clone https://github.com/muhhedahmd/odoo-devKit.git
cd odoo-devKit
python install.py --global --odoo /path/to/odoo
```

Windows:

```powershell
python install.py --global --odoo "C:/odoo/server"
```

Use forward slashes, or double the backslashes. Either works.

What `--global` adds on top of a normal install:

* copies the kit to `~/.odoo-devkit`
* writes an `odoo-devkit` command into the first directory it finds on your
  PATH — `~/.local/bin`, then `~/bin`. If neither exists it creates the first
  one, and if that is not on PATH it prints the exact `setx` line rather than
  leaving you with a command the shell cannot find.
* remembers the Odoo path in `~/.odoo-devkit/config.json`, so you never pass
  `--odoo` again on this machine.

### Then, in every project

```bash
cd /path/to/your/odoo-project
odoo-devkit
```

It copies itself into the project as `odoo-devkit/`, works out the rest, and
builds the indexes. Reload the editor window afterwards.

### Without the global command

Drop the folder in a project by hand and run it in place:

```bash
cp -r /path/to/odoo-devkit /path/to/project/odoo-devkit
cd /path/to/project
python odoo-devkit/install.py
```

On a second run it finds the Odoo path from the project's own `odools.toml`,
so `--odoo` is only needed the first time.

---

## 3. What a successful run looks like

```
odoo-devkit
project: F:\brick-flow
odoo:    F:/src/odoo-19.0  (version 19.0)
addons:  .
frontend modules: village_base, brickflow_cad

  wrote odools.toml
  wrote jsconfig.json
  wrote odoo-devkit/jstypes/odoo-globals.d.ts
  wrote .vscode/settings.json
  wrote .vscode/tasks.json
  wrote .vscode/odoo.xsd
  wrote .vscode/odoo.code-snippets
  extension installed into: VS Code, Cursor
  owl types already present
  built owl index
  built widget index
  built xpath index

Done. Reload the editor window.
```

Indexing takes about eight seconds and happens once; after that the editor
reads JSON.

---

## 4. What it writes, and why

| File | What it is for |
|---|---|
| `odools.toml` | Odoo's own language server config. Carries **both** paths it needs: `odoo_path` gives it `odoo/addons` — base and web — and the separate top-level `addons` holds everything a module really depends on. With only the first, every manifest reports *depends on mail which is not found*. |
| `jsconfig.json` | Maps `@odoo/owl` and `@web/*` onto real files, so OWL imports resolve and the frontend is type-checked. Odoo ships `.d.ts` files; nothing uses them until something maps the module ids onto paths. |
| `.vscode/settings.json` | Chiefly turns **off** `editor.wordBasedSuggestions`. By default the editor pads every completion list with words scraped out of open files, arriving with the same icon as the real ones. That one setting is the difference between a useful list and noise. |
| `.vscode/tasks.json` | The xpath anchors task on `Ctrl+Shift+B`, the removed-API sweep, and an index rebuild. |
| `.vscode/odoo.xsd` | A schema for data files, so `<record>` offers its attributes. Deliberately permissive: unknown attributes pass and a view's `arch` is not checked, because that language is too large to describe and a wrong guess paints every file red. |
| `.vscode/odoo.code-snippets` | 73 snippets. Every prefix starts with `o`, because `depends`, `form`, `list` and `create` are words you type all day. |
| `odoo-devkit/.*.json` | The indexes. Large, machine-specific, git-ignored. |

Files you already have are **kept**, and the skip is reported. `--force`
replaces them.

---

## 5. Verify it works

```bash
python odoo-devkit/xpath_anchors.py base.view_partner_form
```

should print a list of anchors. Then in the editor:

1. Open any view XML in your project.
2. Inside `<field name="` press `Ctrl+Space` → the model's fields.
3. Inside `<xpath expr="` on an inherited view → the parent's nodes.
4. Add `<field name="definitely_not_a_field"/>` to a non-inherited view →
   a warning appears in Problems.

If (4) says nothing, the index has not loaded — see below.

---

## 6. On a second machine

The repository carries no machine paths, so:

```bash
git clone https://github.com/muhhedahmd/odoo-devKit.git
cd odoo-devKit
python install.py --global --odoo /path/to/odoo
```

`--odoo` is needed once per machine: the remembered path lives in
`~/.odoo-devkit/config.json`, which is per user and not in the repository.

### With no network

`install.py --pack DEST` copies the kit with its indexes baked in. Dropped
into a project on a machine with no Odoo checkout and no network, the core
completions work immediately; your own modules are absent from the indexes
until you re-run with `--odoo`.

---

## 7. Keeping it current

```bash
cd /path/to/odoo-devkit
git pull
python install.py --global          # refresh ~/.odoo-devkit and the command
cd /path/to/project
odoo-devkit --force                 # refresh this project
```

Rebuild the indexes alone after adding views or models:

```bash
python odoo-devkit/install.py --indexes-only
```

---

## 8. When something is wrong

**`Could not find an Odoo source tree.`**
Pass `--odoo` with the folder holding both `odoo/release.py` and `addons/`.
Passing a parent or a child of it also works — it looks one level either way.

**`odoo-devkit: command not found`**
The launcher went somewhere not on PATH. The installer prints where it wrote
it and the `setx` line to fix it. Open a new terminal afterwards: PATH is read
at startup.

**Completions are empty**
The extension loads its indexes when the window opens. Install the kit into an
already-open project and there is nothing to read yet — reload the window, or
just keep typing: a request with no index triggers a build and the next one
works.

**`FAILED to build xpath index`**
Almost always `lxml`. The installer prints the error's last lines; the fix is
`python -m pip install lxml`.

**Warnings you believe are wrong**
Tell it. The rule is zero findings on Odoo's own code, and each time that was
not met it was a defect in the checker rather than a threshold to raise.

**The extension is not in my editor**
It is installed by copying into `<editor>/extensions`, which is scanned at
startup. Check `~/.vscode/extensions/local.odoo-xpath-0.0.1` (or
`~/.cursor`, `~/.antigravity-ide`, `~/.windsurf`, `~/.vscode-oss`) and reload.

---

## 9. Removing it

```bash
rm -rf ~/.odoo-devkit
rm -f ~/.local/bin/odoo-devkit ~/.local/bin/odoo-devkit.cmd
rm -rf ~/.vscode/extensions/local.odoo-xpath-0.0.1
```

Per project:

```bash
rm -rf odoo-devkit odools.toml jsconfig.json
```

`.vscode/` is yours — the installer wrote `settings.json`, `tasks.json`,
`odoo.xsd` and `odoo.code-snippets` into it, and leaves anything else alone.

---

## 10. Command reference

```
python install.py [options]

  --odoo PATH        the Odoo source tree; remembered after the first time
  --global           also install a machine-wide copy and an `odoo-devkit`
                     command on PATH
  --force            replace files that already exist
  --indexes-only     rebuild the indexes and nothing else
  --pack DEST        copy the kit with its indexes, ready to carry
  --no-npm           skip the OWL type definitions
```

```
python xpath_anchors.py <view-id | file.xml> [--tree] [--enterprise]
python odoo19_check.py [module …]
python widget_index.py
python owl_index.py
```
