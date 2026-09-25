# odoo-devkit

## One command, anywhere

Set it up on the machine once:

```
python odoo-devkit/install.py --global
```

That copies the kit to `~/.odoo-devkit`, puts an `odoo-devkit` command on
PATH, and remembers where your Odoo source is. From then on, in any project
folder:

```
odoo-devkit
```

It copies itself in and sets the project up. Nothing to download, nothing to
pass — the Odoo path is the one thing worth remembering across projects and it
is the one thing it remembers.

## Or by hand

Drop this folder at the root of a project and run:

```
python odoo-devkit/install.py
```

It finds the Odoo source itself if it is anywhere near, and tells you what to
pass if it is not:

```
python odoo-devkit/install.py --odoo C:/path/to/odoo
```

Nothing in this folder contains a path to any particular machine. The
installer writes them, which is why the same folder works in the next project
and on somebody else's computer.

## On another machine

The folder is portable; the installer is what makes it fit. On a computer that
has never seen it:

```
python odoo-devkit/install.py --global --odoo C:/path/to/odoo
```

`--odoo` is needed the first time on each machine — the remembered path lives
in `~/.odoo-devkit/config.json`, which is per user and not carried in the
folder.

What it handles for you:

* **lxml**, the kit's only dependency. Missing, the view index never builds
  and the extension just goes quiet; the installer now installs it, and says
  so plainly if it cannot.
* **`~/.local/bin`**, which often does not exist on a fresh account. It is
  created, and if it is not on PATH you are told the exact `setx` line rather
  than left with a command the shell cannot find.
* **A failed index** is reported with the error, instead of being swallowed
  behind "Done".

Node and npm are optional: without them the OWL types are skipped and
everything else still works. The `jstypes/node_modules` folder copies across
with the kit, so a machine with no network still gets them.

## What it sets up

**The completions that were missing.** The first thing the installer does is
turn off `editor.wordBasedSuggestions`. By default the editor pads every
completion list with words scraped out of whatever files are open — `about`,
`across`, `already` — and they arrive with the same icon as the real ones.
That single setting is the difference between a useless list and a short one.

**Odoo's language server**, pointed at your source. `odools.toml` carries both
paths it needs: `odoo_path` gives it `odoo/addons` — base and web — and the
separate top-level `addons` directory holds everything a module really depends
on. With only the first, every manifest reports *depends on mail which is not
found* and every `self.env["account.move"]` is an unknown model.

**`<xpath expr="">`, completed from the view you are inheriting.** Nothing
else does this: Odoo's own language server never reads `inherit_id`. The
extension finds the record's `inherit_id`, looks the parent up in an index of
every view in the source, and offers the expressions that would actually
resolve — name matches first, bare tags last and labelled, because a bare tag
is unique only until somebody adds a second one.

**`widget="…"`**, from the widgets Odoo registers, with the module each one
comes from. A widget belonging to a module you do not depend on is marked: it
renders on your machine and not on the customer's, and a widget that silently
falls back to a plain field reads as a styling bug.

**OWL templates, checked.** Every directive name comes out of the OWL bundle
your Odoo ships, and every rule is one of OWL's own compile-time errors:
`t-foreach` without `t-key`, `t-elif` with nothing to follow, `t-component` on
something that is not a `<t>`, `t-model` on a tag that cannot be modelled,
`t-on` with no event name. Plus a warning on any `t-` attribute that is not a
directive at all — the browser keeps those as plain attributes and ignores
them in silence.

Verified against 462 of Odoo's own template files: zero findings.

**TypeScript-grade help for the frontend**, without writing TypeScript. Odoo
ships `.d.ts` files for OWL, the registries and the field widgets, and OWL
publishes its own types. None of it does anything until something maps the
import names onto those files, because `@web/core/registry` is an Odoo module
id and not a path. `jsconfig.json` is that mapping.

**An XML schema for data files**, so `<record>` offers its attributes and a
missing `model=` is caught here rather than at install. Deliberately
permissive: unknown attributes pass, and the inside of a view's `arch` is not
checked at all — that language is too large and too version-dependent to
describe, and a wrong guess would paint every file red.

## Using it

| | |
|---|---|
| `Ctrl+Shift+B` | the xpath anchors for the file you have open |
| `Ctrl+Space` in `expr=""` | the same list, inline |
| `Ctrl+Space` in `widget=""` | the widgets, with their modules |
| `Ctrl+Space` after `t` in a template | the OWL directives |
| `Ctrl+Space` in `t-call=""` or `static template = ""` | the templates that exist |
| Problems panel | the OWL rules, while you type |

From the terminal:

```
python odoo-devkit/xpath_anchors.py base.view_partner_form --tree
python odoo-devkit/widget_index.py
python odoo-devkit/owl_index.py
python odoo-devkit/install.py --indexes-only     # after adding views
```

## Re-run the installer when

* you add a module with a `static/src` (so its import alias exists), or
* the Odoo source moves.

`--force` replaces files you already have; without it they are kept and
reported.

## What it does not do

`from odoo.addons.account.models...` will not resolve, in any editor. Odoo
merges the addon directories into one namespace at runtime and no static
analyser can reproduce that. Open the core file instead — the installer puts
the source on the search path, so `Ctrl+P` reaches it.

The Enterprise source is skipped everywhere it is found. A tool that offers an
anchor or a widget from an Enterprise view is helping you write a module that
installs locally and is missing on the customer's server.
