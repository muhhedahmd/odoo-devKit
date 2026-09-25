# odoo-devkit

Completions and checks for Odoo development, read out of the Odoo source on
your own machine.

Nothing here is a hard-coded list. Every name it offers — every field, view,
widget, menu, group, model and OWL directive — is extracted from the checkout
you point it at, so it is right about the version you actually have rather
than about a version someone remembered when they wrote a plugin.

Built and verified against **Odoo 19**. The indexes work from whatever source
you give them; the removed-API check is 19-specific.

---

## Why

Most of what breaks an Odoo module is a string that nothing validates until
install:

```xml
<field name="secotr_id"/>                     <!-- fails on a build -->
<xpath expr="//notebook" position="inside">   <!-- the parent has none -->
<menuitem parent="account.menu_x"/>           <!-- a module you don't depend on -->
widget="many2many_tag"                         <!-- renders plain, says nothing -->
```

The editor cannot know. Odoo's own language server does not read `inherit_id`
at all. So the answers are indexed from the source and offered where the
string is typed.

---

## What it completes

| Where | From |
|---|---|
| `<field name="…">` | the fields of the model the record is for — **1,302 models** |
| `<xpath expr="…">` | the nodes the inherited view really has — **5,998 views** |
| `position="…"` | the six, each with what it does |
| `widget="…"` | **349 widgets**, with the module and the field types each supports |
| `<widget name="…">` | the view widgets — a different registry, same spelling |
| `parent=` · `action=` | **944 menus** · **1,291 actions** |
| `groups=` | **143 security groups** |
| `ref="…"` | narrowed by the field it sits on: `model_id` wants a model, `inherit_id` a view |
| `domain=` · `context=` | the model's own fields, with `default_` and `search_default_` |
| `ir.model.access.csv` | **1,415 model ids** and the groups — the column read from the header |
| `t-*` in OWL templates | **258 directives**, from the OWL build your Odoo ships |
| `t-call=` · `static template =` | **2,463 templates** that exist |
| `<record …>` | its attributes, from a schema in `assets/odoo.xsd` |
| Python, XML, JS | **73 snippets** |

Anything from a module you have not declared in `depends` is sorted last and
marked, with the reason: that is a failure you meet on someone else's server,
not on yours.

## What it warns about

**A view naming a field the model has not got.** Reported against the model
the node is really in — a field inside a one2many's subview is checked against
the comodel.

**OWL's own compile-time rules**: `t-foreach` without `t-key`, `t-elif` with
nothing to follow, `t-component` on a node that is not a `<t>`, `t-model` on a
tag that cannot be modelled, `t-on` with no event name, `t-raw` (removed in
OWL 2), and any `t-` attribute that is not a directive — the browser keeps
those as plain attributes and ignores them in silence.

**What Odoo 19 removed**, with the emphasis on what fails quietly:
`_sql_constraints` is accepted and then ignored, so the table simply has no
constraint and nothing says so.

### Measured against code that is correct by definition

| | |
|---|---|
| 566 view files across ten core addons | **0 findings** |
| 462 OWL template files | **0 findings** |
| Two deliberate typos in a test view | both caught |

Getting there found six real defects in the checker, not six thresholds to
tune. The notes are in the commit history.

## What it does not do

`from odoo.addons.account.models…` will not resolve, in any editor. Odoo
merges the addon directories into one namespace at runtime and no static
analyser reproduces that. Open the core file instead — the installer puts the
source on the search path.

Inherited views are not field-checked. The model a node lands in comes from
the xpath expression, not from the XML around it, and guessing produced four
false positives in core's own purchase views.

Enterprise is skipped wherever it is found. A tool that offers an anchor or a
widget from an Enterprise view helps you write a module that installs locally
and is missing on the customer's server.

---

## Install

See **[INSTALL.md](INSTALL.md)** for the full walk-through. The short version:

```bash
git clone https://github.com/muhhedahmd/odoo-devKit.git
cd odoo-devKit
python install.py --global --odoo /path/to/odoo
```

Then, in any Odoo project folder:

```bash
odoo-devkit
```

Reload the editor window.

## Requirements

| | |
|---|---|
| Python 3.8+ | you have it if you run Odoo |
| `lxml` | installed for you if missing |
| An Odoo source checkout | the folder holding both `odoo/release.py` and `addons/` |
| VS Code or a fork | Cursor, Antigravity, Windsurf, VSCodium — all detected |
| Node and npm | optional: only the OWL type definitions need them |

## Using it

| | |
|---|---|
| `Ctrl+Space` | in any of the places in the table above |
| `Ctrl+Shift+B` | the xpath anchors for the file you have open |
| Problems panel | the warnings, while you type |
| Run Task → *check for what 19 removed* | the removed-API sweep |

From a terminal:

```bash
python odoo-devkit/xpath_anchors.py base.view_partner_form --tree
python odoo-devkit/odoo19_check.py
python odoo-devkit/install.py --indexes-only     # after adding views
```

## Re-run the installer when

* you add a module with a `static/src` — so its import alias exists, or
* the Odoo source moves.

`--force` replaces files you already have; without it they are kept and the
skip is reported.

## Licence

MIT. See [LICENSE](LICENSE).
