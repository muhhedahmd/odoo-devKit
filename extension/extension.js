// Completion inside <xpath expr="">, taken from the view the record inherits.
//
// Neither VS Code nor Odoo's own language server does this: the server never
// reads inherit_id at all. So the one thing you cannot guess — what the parent
// view actually contains — is the one thing nothing offers. This offers it.
//
// The index is built by tools/xpath_anchors.py and cached to JSON. This file
// only reads that cache, so a keystroke costs a lookup in a Map rather than
// three seconds of walking twelve thousand views.

const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const cp = require("child_process");

// The kit installs itself into <project>/odoo-devkit. Everything below is
// relative to the workspace folder, so the same extension works in any
// project the kit has been dropped into — there is no path to this machine
// anywhere in it.
const KIT = "odoo-devkit";
const CACHE_REL = path.join(KIT, ".xpath_anchors_cache.json");
const WIDGETS_REL = path.join(KIT, ".widget_index.json");
const WIDGET_SCRIPT_REL = path.join(KIT, "widget_index.py");
const OWL_REL = path.join(KIT, ".owl_index.json");
const OWL_SCRIPT_REL = path.join(KIT, "owl_index.py");
const SCRIPT_REL = path.join(KIT, "xpath_anchors.py");

let root = null;
let views = new Map();
let externalIds = new Map();
let modelFields = new Map();
let modelParents = new Map();
let widgets = new Map();
let owl = null;
let building = false;

function log(channel, message) {
  channel.appendLine(`[${new Date().toISOString().slice(11, 19)}] ${message}`);
}

function findRoot() {
  for (const folder of vscode.workspace.workspaceFolders || []) {
    if (fs.existsSync(path.join(folder.uri.fsPath, SCRIPT_REL))) {
      return folder.uri.fsPath;
    }
  }
  return null;
}

function loadCache(channel) {
  const file = path.join(root, CACHE_REL);
  if (!fs.existsSync(file)) return false;
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    views = new Map(Object.entries(data.views || {}));
    externalIds = new Map(Object.entries(data.ids || {}));
    modelFields = new Map(Object.entries(data.fields || {}));
    modelParents = new Map(Object.entries(data.inherits || {}));
    resolved.clear();
    log(channel,
      `index loaded: ${views.size} views, ${externalIds.size} ids, ` +
      `${modelFields.size} models`);
    return views.size > 0;
  } catch (err) {
    log(channel, `index unreadable: ${err.message}`);
    return false;
  }
}

function loadWidgets(channel) {
  const file = path.join(root, WIDGETS_REL);
  if (!fs.existsSync(file)) return false;
  try {
    widgets = new Map(Object.entries(JSON.parse(fs.readFileSync(file, "utf8"))));
    log(channel, `widgets loaded: ${widgets.size}`);
    return widgets.size > 0;
  } catch (err) {
    log(channel, `widget index unreadable: ${err.message}`);
    return false;
  }
}

function buildWidgets(channel) {
  const python = vscode.workspace
    .getConfiguration("odooXpath")
    .get("pythonPath", "python");
  return new Promise((resolve) => {
    cp.execFile(
      python,
      [WIDGET_SCRIPT_REL],
      { cwd: root, maxBuffer: 64 * 1024 * 1024 },
      (err, _out, stderr) => {
        if (err) log(channel, `widget index failed: ${stderr || err.message}`);
        resolve(loadWidgets(channel));
      }
    );
  });
}

// What the module holding this file declares it depends on. A widget from a
// module that is not in there renders here and not on the customer's server,
// which looks like a CSS problem and is really a missing dependency.
function dependsOf(filePath) {
  let probe = path.dirname(filePath);
  for (let i = 0; i < 8; i += 1) {
    const manifest = path.join(probe, "__manifest__.py");
    if (fs.existsSync(manifest)) {
      try {
        const text = fs.readFileSync(manifest, "utf8");
        const block = /["\']depends["\']\s*:\s*\[([^\]]*)\]/.exec(text);
        const names = block
          ? (block[1].match(/["\']([\w.]+)["\']/g) || []).map((q) =>
              q.slice(1, -1)
            )
          : [];
        return { module: path.basename(probe), depends: new Set(names) };
      } catch (err) {
        return null;
      }
    }
    const parent = path.dirname(probe);
    if (parent === probe) break;
    probe = parent;
  }
  return null;
}

// base and web are in every module's graph whether or not they are written
// down, so a widget from either is always safe.
const ALWAYS = new Set(["base", "web"]);

function widgetItems(document, wantViewWidgets) {
  const here = dependsOf(document.uri.fsPath);
  const items = [];
  for (const [name, info] of widgets) {
    const isView = info.kind === "view_widgets";
    if (isView !== wantViewWidgets) continue;

    const reachable =
      !here ||
      ALWAYS.has(info.module) ||
      info.module === here.module ||
      here.depends.has(info.module);

    const item = new vscode.CompletionItem(
      name,
      vscode.CompletionItemKind.Value
    );
    const types = (info.types || []).join(", ");
    item.detail =
      `${info.module}${types ? " — " + types : ""}` +
      (reachable ? "" : "   (not in depends)");
    item.documentation = new vscode.MarkdownString(
      reachable
        ? `Registered by **${info.module}**` +
            (types ? `\n\nField types: ${types}` : "")
        : `Registered by **${info.module}**, which **${here.module}** does ` +
            `not depend on.\n\nIt will render on this machine and not on a ` +
            `server without that module — and a widget that silently falls ` +
            `back to the plain field looks like a styling bug.`
    );
    if (!reachable) item.tags = [vscode.CompletionItemTag.Deprecated];
    // Reachable first, web before the rest, then alphabetical.
    item.sortText = `${reachable ? 0 : 1}${ALWAYS.has(info.module) ? 0 : 1}${name}`;
    items.push(item);
  }
  return items;
}

function build(channel, rebuild) {
  if (building) return Promise.resolve(false);
  building = true;
  const python = vscode.workspace
    .getConfiguration("odooXpath")
    .get("pythonPath", "python");
  const args = [SCRIPT_REL, "base.view_partner_form", "--json"];
  if (rebuild) args.push("--rebuild");

  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "Odoo: indexing views…" },
    () =>
      new Promise((resolve) => {
        cp.execFile(
          python,
          args,
          { cwd: root, maxBuffer: 64 * 1024 * 1024 },
          (err, _stdout, stderr) => {
            building = false;
            if (err) {
              log(channel, `index failed: ${stderr || err.message}`);
              vscode.window.showErrorMessage(
                "Odoo xpath: could not build the index. See the Odoo xpath output."
              );
              resolve(false);
              return;
            }
            resolve(loadCache(channel));
          }
        );
      })
  );
}





// ── <field name="…"> ───────────────────────────────────────────────────
//
// The one that covers accounting, sales and purchase in the same stroke: it
// knows nothing about account.move in particular, it knows what fields the
// model in front of it has. A field name is a string nothing checks, and the
// wrong one fails the install with "Field X does not exist in model Y" —
// after a push, on a build.

// Which model this record is for. Either its own <field name="model">, or,
// for an inherited view, the model of the view it inherits.
function recordModel(text, offset) {
  const open = text.lastIndexOf("<record", offset);
  const scope = open === -1 ? text : text.slice(open, offset + 4000);
  const own = /name\s*=\s*"model"\s*>\s*([\w.]+)\s*</.exec(scope);
  if (own) return own[1];
  const ref = inheritedRef(text, offset);
  if (ref) {
    const view = views.get(ref);
    if (view && view.model) return view.model;
  }
  // A <templates> file has no record; a t-name is not a model.
  return null;
}

const FIELD_ICON = {
  Many2one: vscode.CompletionItemKind.Reference,
  One2many: vscode.CompletionItemKind.Reference,
  Many2many: vscode.CompletionItemKind.Reference,
  Boolean: vscode.CompletionItemKind.Constant,
  Selection: vscode.CompletionItemKind.EnumMember,
  Monetary: vscode.CompletionItemKind.Unit,
};

function fieldItems(model) {
  const fields = modelFields.get(model);
  if (!fields) return [];
  return Object.entries(fields).map(([name, [type, label, comodel]]) => {
    const item = new vscode.CompletionItem(
      name,
      FIELD_ICON[type] || vscode.CompletionItemKind.Field
    );
    item.detail = `${type}${comodel ? " → " + comodel : ""}${label ? "  ·  " + label : ""}`;
    item.documentation = new vscode.MarkdownString(
      `**${model}.${name}**\n\n${type}` +
        (comodel ? ` of \`${comodel}\`` : "") +
        (label ? `\n\n${label}` : "")
    );
    // Stored, named fields before the computed plumbing, roughly: the ones
    // with a label are the ones somebody meant a user to see.
    item.sortText = `${label ? 0 : 1}${name}`;
    return item;
  });
}



// ── ref=, domain= and context= ─────────────────────────────────────────
//
// `ref` takes an external id, and which kind depends entirely on the field
// holding it: model_id wants a model, groups wants groups, inherit_id wants a
// view. Offering all four thousand ids for every one of them is the same as
// offering none.

const REF_KIND = {
  model_id: "model",
  res_model_id: "model",
  binding_model_id: "model",
  group_id: "group",
  groups_id: "group",
  groups: "group",
  implied_ids: "group",
  view_id: "view",
  inherit_id: "view",
  search_view_id: "view",
  view_ids: "view",
  action_id: "action",
  binding_action_id: "action",
  menu_id: "menu",
  parent_menu_id: "menu",
};

function viewItems(document) {
  const here = dependsOf(document.uri.fsPath);
  const items = [];
  for (const [xmlid, view] of views) {
    const module = xmlid.split(".")[0];
    const reachable =
      !here || ALWAYS.has(module) || module === here.module ||
      here.depends.has(module);
    const item = new vscode.CompletionItem(
      xmlid,
      vscode.CompletionItemKind.Struct
    );
    item.detail = (view.model || "") + (reachable ? "" : "   (not in depends)");
    if (!reachable) item.tags = [vscode.CompletionItemTag.Deprecated];
    item.sortText = `${reachable ? 0 : 1}${xmlid}`;
    items.push(item);
  }
  return items;
}

// The field the ref sits on: <field name="model_id" ref="…"/>
function refKindFor(before) {
  const open = before.lastIndexOf("<");
  if (open === -1) return null;
  const chunk = before.slice(open);
  const named = /\bname\s*=\s*"([\w.]+)"/.exec(chunk);
  return named ? REF_KIND[named[1]] || null : null;
}

// Inside domain= or context=, what is wanted is a field of this record's
// model — written as a string in a Python-ish expression that nothing
// completes on its own.
function domainItems(model, prefixes) {
  const fields = fieldsOf(model);
  const items = [];
  for (const [name, [type, label, comodel]] of Object.entries(fields)) {
    for (const prefix of prefixes) {
      const item = new vscode.CompletionItem(
        prefix + name,
        vscode.CompletionItemKind.Field
      );
      item.detail = `${type}${comodel ? " → " + comodel : ""}${label ? "  ·  " + label : ""}`;
      item.sortText = `${label ? 0 : 1}${prefix}${name}`;
      items.push(item);
    }
  }
  return items;
}

// ── does this model really have that field? ────────────────────────────
//
// A field name in a view is a string checked by nothing until install, where
// it fails with "Field X does not exist in model Y". The index knows the
// answer, so the question can be asked here.
//
// Mixins are the reason this needs care. account.move declares no message_ids
// — mail.thread does, and account.move only lists it in _inherit. Resolve the
// parents or every chatter in Odoo gets flagged.

const resolved = new Map();

function fieldsOf(model, seen) {
  if (resolved.has(model)) return resolved.get(model);
  seen = seen || new Set();
  if (seen.has(model)) return {};
  seen.add(model);

  const own = modelFields.get(model) || {};
  const merged = Object.assign({}, own);
  for (const parent of modelParents.get(model) || []) {
    const inherited = fieldsOf(parent, seen);
    for (const name of Object.keys(inherited)) {
      if (!(name in merged)) merged[name] = inherited[name];
    }
  }
  if (seen.size === 1) resolved.set(model, merged);
  return merged;
}

// Fields Odoo puts on every model without declaring them in Python.
const MAGIC_FIELDS = new Set([
  "id", "display_name", "create_uid", "create_date", "write_uid",
  "write_date", "__last_update", "sequence",
]);

// A model we clearly know too little about is not evidence of anything.
const ENOUGH_FIELDS = 5;

// Blank out comments, keeping every offset where it was: commented-out
// code is where a field that no longer exists is most likely to be, so
// reading it gives the most confident kind of wrong answer.
function withoutComments(text) {
  return text.replace(/<!--[\s\S]*?-->/g, (match) =>
    match.replace(/[^\n]/g, " ")
  );
}

function diagnoseView(document) {
  if (!modelFields.size) return [];
  const p = document.uri.fsPath.replace(/\\/g, "/");
  if (!p.endsWith(".xml") || /\/static\//.test(p)) return [];

  const text = withoutComments(document.getText());
  const out = [];

  // One record at a time: each has its own model.
  const RECORD = /<record\b[^>]*\bmodel\s*=\s*"ir\.ui\.view"[^>]*>/g;
  let record;
  while ((record = RECORD.exec(text))) {
    const close = text.indexOf("</record>", record.index);
    const end = close === -1 ? text.length : close;
    const scope = text.slice(record.index, end);

    // An inherited view's nodes are placed by an xpath expression, and the
    // model they land in comes from that string rather than from the XML
    // around them. Until that is resolved, they are not checked.
    if (/name\s*=\s*"inherit_id"/.test(scope)) continue;

    const model = recordModel(text, record.index + record[0].length + 10);
    if (!model) continue;
    const fields = fieldsOf(model);
    if (Object.keys(fields).length < ENOUGH_FIELDS) continue;

    // Only inside the arch: the fields before it belong to ir.ui.view.
    const archTag = /<field\b[^>]*\bname\s*=\s*"arch"[^>]*>/.exec(scope);
    if (!archTag) continue;
    // After the arch tag, not at it: otherwise `name="arch"` is read as a
    // field of the model and reported on every view in Odoo.
    const archAt = archTag.index + archTag[0].length;

    // The model changes inside a subview, so it is a stack keyed by depth.
    const stack = [{ depth: 0, fields, model }];
    let depth = 0;

    TAG.lastIndex = archAt;
    let tag;
    while ((tag = TAG.exec(scope))) {
      const [, closing, name, body, selfClose] = tag;
      if (closing) {
        depth -= 1;
        while (stack.length > 1 && stack[stack.length - 1].depth > depth) {
          stack.pop();
        }
        continue;
      }
      const opens = !selfClose && !/^(br|img|hr|meta|link|attribute)$/i.test(name);

      if (name === "field") {
        const attr = /\bname\s*=\s*"([^"]*)"/.exec(body);
        const value = attr && attr[1];
        const current = stack[stack.length - 1];
        // A null field map means the frame is one we are blind in — a
        // subview whose model could not be resolved.
        const known = current.fields && value ? current.fields[value] : null;
        // position="attributes" holds <attribute> children, not a subview,
        // and the field being patched may be one this module is adding.
        const patching = /\bposition\s*=\s*"attributes"/.test(body);

        if (
          current.fields &&
          value &&
          /^[a-z]\w*$/.test(value) &&
          !MAGIC_FIELDS.has(value)
        ) {
          if (!known && !patching) {
            const at = tag.index + body.indexOf(attr[0]) + name.length + 1;
            const start = record.index + at;
            out.push(
              Object.assign(
                new vscode.Diagnostic(
                  new vscode.Range(
                    document.positionAt(start),
                    document.positionAt(start + attr[0].length)
                  ),
                  `${current.model} has no field "${value}".\n` +
                    `Install fails with "Field ${value} does not exist in ` +
                    `model ${current.model}".`,
                  vscode.DiagnosticSeverity.Warning
                ),
                { source: "odoo", code: "odoo-unknown-field" }
              )
            );
          }
        }

        // Children mean a subview, and a subview is the model at the other
        // end of this field. If that model cannot be resolved, checking
        // stops inside it rather than continuing against the wrong one.
        if (value && opens) {
          const comodel = known && known[2] ? known[2] : null;
          const inner = comodel ? fieldsOf(comodel) : null;
          const enough = inner && Object.keys(inner).length >= ENOUGH_FIELDS;
          stack.push({
            depth: depth + 1,
            fields: enough ? inner : null,
            model: comodel || "?",
          });
        }
      }
      if (opens) depth += 1;
    }
  }
  return out;
}

// ── ir.model.access.csv ────────────────────────────────────────────────
//
// Two of its columns are external ids and neither is checked while you type.
// model_id:id is the worse one: those ids are generated by Odoo —
// model_village_unit for village.unit — so there is nothing on disk to copy
// them from and they get retyped from memory onto every line. One wrong and
// the module will not install.
//
// The column is found from the header rather than by position, because the
// order is a convention and not a rule.
function accessCsvColumn(document, position) {
  const name = path.basename(document.uri.fsPath).toLowerCase();
  if (name !== "ir.model.access.csv") return null;
  if (position.line === 0) return null;

  const header = document.lineAt(0).text.split(",").map((c) => c.trim());
  const before = document.lineAt(position.line).text.slice(0, position.character);
  const column = before.split(",").length - 1;
  const heading = header[column] || "";

  if (heading === "model_id:id") return "model";
  if (heading === "group_id:id") return "group";
  return null;
}

function csvItems(document, kind) {
  const here = dependsOf(document.uri.fsPath);
  const items = [];
  for (const [xmlid, info] of externalIds) {
    if (info.kind !== kind) continue;
    const reachable =
      !here ||
      ALWAYS.has(info.module) ||
      info.module === here.module ||
      here.depends.has(info.module);

    const item = new vscode.CompletionItem(
      xmlid,
      kind === "model"
        ? vscode.CompletionItemKind.Class
        : vscode.CompletionItemKind.Interface
    );
    item.detail =
      (info.name ? info.name + "  ·  " : "") +
      info.module +
      (reachable ? "" : "   (not in depends)");
    if (!reachable) {
      item.tags = [vscode.CompletionItemTag.Deprecated];
      item.documentation = new vscode.MarkdownString(
        `Declared by **${info.module}**, which **${here.module}** does not ` +
          `depend on. The module will not install.`
      );
    }
    item.sortText = `${reachable ? 0 : 1}${here && info.module === here.module ? 0 : 1}${xmlid}`;
    items.push(item);
  }
  return items;
}

// ── external ids: a menuitem's parent, action and groups ───────────────
//
// All three are strings nothing checks. A wrong one fails at install with
// "External ID not found", which names what you typed and not what exists —
// and an id from a module you forgot to depend on fails the same way, on the
// customer's server rather than yours.

const KIND_LABEL = { menu: "menu", action: "action", group: "group" };

function externalIdItems(document, kind, currentWord) {
  const here = dependsOf(document.uri.fsPath);
  const items = [];
  for (const [xmlid, info] of externalIds) {
    if (info.kind !== kind) continue;

    const reachable =
      !here ||
      ALWAYS.has(info.module) ||
      info.module === here.module ||
      here.depends.has(info.module);

    // Inside its own module Odoo accepts the bare id, and that is what core
    // writes; everything else has to carry the module.
    const own = here && info.module === here.module;
    const insert = own ? xmlid.split(".").slice(1).join(".") : xmlid;

    const item = new vscode.CompletionItem(
      insert,
      kind === "menu"
        ? vscode.CompletionItemKind.Folder
        : kind === "group"
        ? vscode.CompletionItemKind.Interface
        : vscode.CompletionItemKind.Event
    );
    item.detail =
      (info.name ? info.name + "  ·  " : "") +
      info.module +
      (reachable ? "" : "   (not in depends)");
    item.documentation = new vscode.MarkdownString(
      reachable
        ? `\`${xmlid}\`` + (info.name ? `\n\n${info.name}` : "")
        : `\`${xmlid}\`\n\nDeclared by **${info.module}**, which ` +
          `**${here.module}** does not depend on. The install fails with ` +
          `*External ID not found* — on a server that has not got that ` +
          `module, which may not be yours.`
    );
    if (!reachable) item.tags = [vscode.CompletionItemTag.Deprecated];
    item.filterText = xmlid;
    item.sortText = `${reachable ? 0 : 1}${own ? 0 : 1}${xmlid}`;
    items.push(item);
  }
  return items;
}

// groups= holds a comma-separated list, so only the part after the last
// comma is being typed.
function afterLastComma(value) {
  const at = value.lastIndexOf(",");
  return at === -1 ? value : value.slice(at + 1).trim();
}

// ── OWL templates ──────────────────────────────────────────────────────
//
// Everything below is driven by tools/.owl_index.json, which is extracted
// from the OWL bundle Odoo 19 actually ships and from core's own templates.
// The rules are OWL's own compile-time errors, reported here instead of in
// the browser console.

function loadOwl(channel) {
  const file = path.join(root, OWL_REL);
  if (!fs.existsSync(file)) return false;
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    const known = new Set([...(data.directives || []), ...(data.from_core || [])]);
    owl = {
      known,
      prefixed: data.prefixed || [],
      templates: new Set(data.templates || []),
      rules: Object.fromEntries((data.rules || []).map((r) => [r.test, r])),
    };
    log(channel, `owl index: ${known.size} directives, ${owl.templates.size} templates`);
    return true;
  } catch (err) {
    log(channel, `owl index unreadable: ${err.message}`);
    return false;
  }
}

function buildOwl(channel) {
  const python = vscode.workspace
    .getConfiguration("odooXpath")
    .get("pythonPath", "python");
  return new Promise((resolve) => {
    cp.execFile(python, [OWL_SCRIPT_REL], { cwd: root, maxBuffer: 64 * 1024 * 1024 },
      (err, _o, stderr) => {
        if (err) log(channel, `owl index failed: ${stderr || err.message}`);
        resolve(loadOwl(channel));
      });
  });
}

// An OWL template lives under static/src. Server-side QWeb lives in views/
// and report/ and has a different, larger directive set, so checking it
// against OWL's list would invent errors.
function isOwlTemplate(document) {
  const p = document.uri.fsPath.replace(/\\/g, "/");
  return /\/static\/(src|tests)\//.test(p) && p.endsWith(".xml");
}

function isKnownDirective(name) {
  if (owl.known.has(name)) return true;
  return owl.prefixed.some((p) => name.startsWith(p) && name.length > p.length);
}

// Single quotes are legal and core uses them — and a value like
// t-if='a > 1' puts a `>` inside the tag, which is why the scanner has
// to know about both quote styles or it ends the tag in the wrong place.
const TAG = /<(\/?)([\w.:-]+)((?:[^<>"']|"[^"]*"|'[^']*')*?)(\/?)>/g;
const ATTR = /([\w.:@-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
const MODEL_TAGS = new Set(["input", "textarea", "select"]);
// t-on and t-custom carry no meaning without a suffix; t-att and t-attf do,
// because both accept an object of attributes.
const NEEDS_SUFFIX = new Set(["t-on", "t-custom"]);

function diagnose(document) {
  if (!owl || !isOwlTemplate(document)) return [];
  const text = document.getText();
  const out = [];
  const depth = [];        // tag names, to know where we are
  const previous = [];     // the directives of the last sibling, per depth

  const add = (rule, start, end, extra) => {
    const spec = owl.rules[rule];
    if (!spec) return;
    const item = new vscode.Diagnostic(
      new vscode.Range(document.positionAt(start), document.positionAt(end)),
      (extra ? `${spec.message}: ${extra}` : spec.message) + `\n${spec.why}`,
      spec.severity === "error"
        ? vscode.DiagnosticSeverity.Error
        : vscode.DiagnosticSeverity.Warning
    );
    item.source = "owl";
    item.code = spec.id;
    out.push(item);
  };

  TAG.lastIndex = 0;
  let match;
  while ((match = TAG.exec(text))) {
    const [whole, closing, tag, body, selfClose] = match;
    const bodyStart = match.index + 1 + closing.length + tag.length;

    if (closing) {
      depth.pop();
      continue;
    }

    const attrs = new Map();
    ATTR.lastIndex = 0;
    let attr;
    while ((attr = ATTR.exec(body))) {
      attrs.set(attr[1], {
        value: attr[2] !== undefined ? attr[2] : attr[3],
        start: bodyStart + attr.index,
        end: bodyStart + attr.index + attr[1].length,
      });
    }

    for (const [name, at] of attrs) {
      if (!name.startsWith("t-")) continue;
      if (NEEDS_SUFFIX.has(name)) add("bare_prefixed", at.start, at.end);
      else if (name === "t-raw") add("t_raw", at.start, at.end);
      else if (!isKnownDirective(name)) add("unknown_directive", at.start, at.end, name);
    }

    if (attrs.has("t-foreach") && !attrs.has("t-key")) {
      const at = attrs.get("t-foreach");
      add("foreach_without_key", at.start, at.end);
    }
    if (attrs.has("t-component") && tag !== "t") {
      const at = attrs.get("t-component");
      add("component_not_on_t", at.start, at.end, `<${tag}>`);
    }
    if (attrs.has("t-set-slot") && tag !== "t") {
      const at = attrs.get("t-set-slot");
      add("setslot_not_on_t", at.start, at.end, `<${tag}>`);
    }
    if (attrs.has("t-model") && !MODEL_TAGS.has(tag)) {
      const at = attrs.get("t-model");
      add("model_bad_tag", at.start, at.end, `<${tag}>`);
    }

    // t-elif / t-else must follow a t-if or t-elif on the previous sibling.
    //
    // Not inside an <xpath>, though. There the node is a patch applied to
    // another template, and its t-if may be added by a different block
    // entirely — core does exactly that in contact_image_field.xml. The
    // sibling only exists after inheritance, which this cannot see.
    const level = depth.length;
    const prior = previous[level];
    const patching = depth.includes("xpath");
    if (!patching && (attrs.has("t-elif") || attrs.has("t-else"))) {
      const key = attrs.has("t-elif") ? "t-elif" : "t-else";
      const at = attrs.get(key);
      if (!prior || !(prior.has("t-if") || prior.has("t-elif"))) {
        add("elif_without_if", at.start, at.end);
      }
    }
    previous[level] = new Set(attrs.keys());

    if (!selfClose && !/^(br|img|input|hr|meta|link)$/i.test(tag)) {
      depth.push(tag);
      previous[depth.length] = null; // a new level starts with no sibling
    }
  }
  return out;
}

function owlAttributeItems() {
  const items = [];
  for (const name of owl.known) {
    if (name.endsWith("-")) continue; // a prefix, not a name
    const item = new vscode.CompletionItem(
      name,
      vscode.CompletionItemKind.Property
    );
    item.insertText = new vscode.SnippetString(`${name}="$1"$0`);
    item.detail = "OWL";
    items.push(item);
  }
  for (const prefix of owl.prefixed) {
    const item = new vscode.CompletionItem(
      prefix + "…",
      vscode.CompletionItemKind.Property
    );
    item.insertText = new vscode.SnippetString(`${prefix}\${1:name}="$2"$0`);
    item.filterText = prefix;
    item.detail = "OWL — needs a suffix";
    items.push(item);
  }
  return items;
}

// Inside a tag, typing an attribute name rather than sitting in a value.
function attributeNameContext(before) {
  const open = before.lastIndexOf("<");
  if (open === -1) return null;
  const chunk = before.slice(open);
  if (chunk.includes(">")) return null;
  if ((chunk.match(/"/g) || []).length % 2 === 1) return null; // in a value
  const tag = /^<\s*([\w.:-]+)/.exec(chunk);
  if (!tag) return null;
  const word = /(\S*)$/.exec(chunk)[1];
  return { tag: tag[1], word };
}

// ── reading the document ───────────────────────────────────────────────

// Which attribute of which tag the cursor sits in, if any.
function attributeContext(before) {
  const open = before.lastIndexOf("<");
  if (open === -1) return null;
  const chunk = before.slice(open);
  if (chunk.includes(">")) return null; // the tag is already closed
  const tag = /^<\s*([\w:.-]+)/.exec(chunk);
  if (!tag) return null;
  // An odd number of quotes means we are inside a value.
  const quotes = (chunk.match(/"/g) || []).length;
  if (quotes % 2 === 0) return null;
  const attr = /([\w:.-]+)\s*=\s*"[^"]*$/.exec(chunk);
  if (!attr) return null;
  return { tag: tag[1], attr: attr[1] };
}

// The inherit_id of the record the cursor is in — the nearest one that opens
// before it, because a file holds several records and the last one in the
// file is usually not the one being edited.
function inheritedRef(text, offset) {
  const recordOpen = text.lastIndexOf("<record", offset);
  if (recordOpen === -1) return null;
  const scope = text.slice(recordOpen, offset);
  const match = /name\s*=\s*"inherit_id"[^>]*?ref\s*=\s*"([^"]+)"/.exec(scope);
  if (match) return match[1];
  // Attribute order is not fixed: ref may be written before name.
  const reversed = /ref\s*=\s*"([^"]+)"[^>]*?name\s*=\s*"inherit_id"/.exec(scope);
  return reversed ? reversed[1] : null;
}

const RANK_NOTE = {
  0: "by name — stable",
  1: "by class",
  2: "bare tag — unique today only",
};

function itemsFor(ref, channel) {
  const view = views.get(ref);
  if (!view) {
    log(channel, `no such view in the index: ${ref}`);
    return [];
  }
  return (view.anchors || []).map(([rank, expr, tag], index) => {
    const item = new vscode.CompletionItem(
      expr,
      vscode.CompletionItemKind.Reference
    );
    item.detail = `<${tag}> — ${RANK_NOTE[rank] || ""}`;
    item.documentation = new vscode.MarkdownString(
      `From **${ref}** *(${view.model || "?"})*` +
        (view.enterprise
          ? "\n\n**Enterprise view.** Inheriting it gives a module that " +
            "installs here and is missing on the customer's server."
          : "")
    );
    // Name-matched anchors first, bare tags last, original order within.
    item.sortText = `${rank}${String(index).padStart(4, "0")}`;
    item.filterText = expr;
    return item;
  });
}

const POSITIONS = [
  ["after", "insert after the matched node"],
  ["before", "insert before it"],
  ["inside", "append inside it"],
  ["replace", "replace it — the original is gone, including other modules' additions"],
  ["attributes", "change its attributes; an empty value removes one"],
  ["move", "relocate an existing node rather than copying it"],
];

// ── wiring ─────────────────────────────────────────────────────────────

function activate(context) {
  const channel = vscode.window.createOutputChannel("Odoo xpath");
  context.subscriptions.push(channel);

  root = findRoot();
  if (!root) {
    log(channel, "no workspace folder contains tools/xpath_anchors.py");
    return;
  }
  log(channel, `root: ${root}`);
  if (!loadCache(channel)) build(channel, false);
  if (!loadWidgets(channel)) buildWidgets(channel);
  if (!loadOwl(channel)) buildOwl(channel);

  // Diagnostics for OWL templates: OWL's own compile-time rules, reported
  // while typing instead of in the browser console after a rebuild.
  const owlDiagnostics = vscode.languages.createDiagnosticCollection("owl");
  context.subscriptions.push(owlDiagnostics);
  let debounce = null;
  const refresh = (document) => {
    if (!document || document.languageId !== "xml") return;
    owlDiagnostics.set(
      document.uri,
      isOwlTemplate(document) ? diagnose(document) : diagnoseView(document)
    );
  };
  const refreshSoon = (document) => {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(() => refresh(document), 300);
  };
  vscode.workspace.textDocuments.forEach(refresh);
  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument(refresh),
    vscode.workspace.onDidChangeTextDocument((e) => refreshSoon(e.document)),
    vscode.workspace.onDidCloseTextDocument((d) => owlDiagnostics.delete(d.uri))
  );

  const provider = vscode.languages.registerCompletionItemProvider(
    { language: "xml", scheme: "file" },
    {
      provideCompletionItems(document, position) {
        const before = document.getText(
          new vscode.Range(new vscode.Position(0, 0), position)
        );
        const context_ = attributeContext(before);

        // t-call, and the OWL attribute names, before the generic handling.
        //
        // If the index was not ready when the window opened — a fresh
        // project, or the kit installed while the editor was already
        // running — build it now rather than staying silent until the next
        // reload. The first request after that returns nothing; the one
        // after it works.
        if (!owl && isOwlTemplate(document)) buildOwl(channel);
        if (owl && isOwlTemplate(document)) {
          if (context_ && context_.attr === "t-call") {
            return [...owl.templates].map((name) => {
              const item = new vscode.CompletionItem(
                name,
                vscode.CompletionItemKind.File
              );
              item.detail = "template";
              return item;
            });
          }
          if (!context_) {
            const naming = attributeNameContext(before);
            if (naming && naming.word.startsWith("t")) return owlAttributeItems();
          }
        }

        if (!context_) return;

        if (context_.attr === "position") {
          return POSITIONS.map(([value, note]) => {
            const item = new vscode.CompletionItem(
              value,
              vscode.CompletionItemKind.EnumMember
            );
            item.detail = note;
            return item;
          });
        }

        // ref=, pointed at what the field it sits on actually wants.
        if (context_.attr === "ref" && externalIds.size) {
          const kind = refKindFor(before);
          if (kind === "view") return viewItems(document);
          if (kind) return externalIdItems(document, kind);
        }

        // domain= and context=, completed with the model's own fields.
        if (
          (context_.attr === "domain" || context_.attr === "context") &&
          modelFields.size &&
          !isOwlTemplate(document)
        ) {
          const model = recordModel(document.getText(), before.length);
          if (model && modelFields.has(model)) {
            return domainItems(
              model,
              context_.attr === "domain"
                ? [""]
                : ["default_", "search_default_"]
            );
          }
        }

        // <field name="…"> against the record's model.
        if (
          modelFields.size &&
          context_.tag === "field" &&
          context_.attr === "name" &&
          !isOwlTemplate(document)
        ) {
          const model = recordModel(document.getText(), before.length);
          if (model) {
            const items = fieldItems(model);
            if (items.length) return items;
          }
        }

        // A menuitem's three pointers, and groups= anywhere.
        if (externalIds.size) {
          if (context_.tag === "menuitem" && context_.attr === "parent") {
            return externalIdItems(document, "menu");
          }
          if (context_.tag === "menuitem" && context_.attr === "action") {
            return externalIdItems(document, "action");
          }
          if (context_.attr === "groups") {
            return externalIdItems(document, "group");
          }
        }

        if (context_.attr === "widget") {
          if (!widgets.size) {
            buildWidgets(channel);
            return;
          }
          return widgetItems(document, false);
        }

        if (context_.tag === "widget" && context_.attr === "name") {
          if (!widgets.size) {
            buildWidgets(channel);
            return;
          }
          return widgetItems(document, true);
        }

        if (context_.attr !== "expr" || context_.tag !== "xpath") return;

        const ref = inheritedRef(document.getText(), before.length);
        if (!ref) {
          log(channel, "cursor is in an xpath with no inherit_id above it");
          return;
        }
        if (!views.size) {
          build(channel, false);
          return;
        }
        return itemsFor(ref, channel);
      },
    },
    '"',
    "/",
    "@",
    "["
  );
  context.subscriptions.push(provider);

  // `static template = "…"` in a component. The name is a string and
  // nothing checks it: get it wrong and OWL throws "Cannot find template"
  // at mount, in the browser, with the component already half set up. The
  // names come from the same t-name index the XML side uses.
  const jsProvider = vscode.languages.registerCompletionItemProvider(
    [
      { language: "javascript", scheme: "file" },
      { language: "typescript", scheme: "file" },
    ],
    {
      provideCompletionItems(document, position) {
        if (!owl) return;
        const line = document.lineAt(position.line).text.slice(0, position.character);
        // `template = "`, `static template = "`, or a t-call in a string.
        if (!/(template|t-call)\s*[=:]\s*["'`][^"'`]*$/.test(line)) return;
        return [...owl.templates].map((name) => {
          const item = new vscode.CompletionItem(
            name,
            vscode.CompletionItemKind.File
          );
          item.detail = "OWL template";
          return item;
        });
      },
    },
    '"',
    "'",
    "."
  );
  context.subscriptions.push(jsProvider);

  // The ACL file. VS Code calls it csv or plaintext depending on what is
  // installed, so both are claimed and the filename decides.
  const csvProvider = vscode.languages.registerCompletionItemProvider(
    [
      { language: "csv", scheme: "file" },
      { language: "plaintext", scheme: "file" },
    ],
    {
      provideCompletionItems(document, position) {
        if (!externalIds.size) return;
        const kind = accessCsvColumn(document, position);
        return kind ? csvItems(document, kind) : undefined;
      },
    },
    ",",
    "_",
    "."
  );
  context.subscriptions.push(csvProvider);

  context.subscriptions.push(
    vscode.commands.registerCommand("odooXpath.rebuild", async () => {
      const ok = await build(channel, true);
      await buildWidgets(channel);
      await buildOwl(channel);
      vscode.window.showInformationMessage(
        ok
          ? `Odoo: ${views.size} views and ${widgets.size} widgets indexed.`
          : "Odoo: indexing failed."
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("odooXpath.showParent", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const ref = inheritedRef(
        editor.document.getText(),
        editor.document.offsetAt(editor.selection.active)
      );
      if (!ref) {
        vscode.window.showWarningMessage("No inherit_id above the cursor.");
        return;
      }
      const view = views.get(ref);
      if (!view) {
        vscode.window.showWarningMessage(`${ref} is not in the index.`);
        return;
      }
      const document = await vscode.workspace.openTextDocument(
        vscode.Uri.file(view.path)
      );
      await vscode.window.showTextDocument(document, { preview: true });
    })
  );

  // Our own views change; core does not. A save marks the index stale and the
  // next build picks it up — rebuilding on every save would cost three
  // seconds each time for a file you are still editing.
  const watcher = vscode.workspace.createFileSystemWatcher("**/*.xml");
  let timer = null;
  const schedule = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => build(channel, false), 5000);
  };
  watcher.onDidCreate(schedule);
  watcher.onDidDelete(schedule);
  context.subscriptions.push(watcher);
}

function deactivate() {}

module.exports = { activate, deactivate };
