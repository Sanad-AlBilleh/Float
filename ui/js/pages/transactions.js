// transactions.html: record, list, edit and delete income and expenses (FR-05–08).
// Rows created by a shared expense or a settlement are managed by the households service and are
// shown read-only here, as in A1.
"use strict";

(async () => {
  const { h, icon, money, parseMoney, showProblem, today, field } = UI;
  const me = await Api.me();
  const main = UI.shell("Transactions", me);
  const MANAGERS = { bill: "bill", shared: "shared expense", settlement: "settlement" };
  let categories = [];
  let editing = null; // the transaction being edited, or null for a new one

  const kind = h("select", { id: "kind", name: "kind" }, h("option", { value: "expense" }, "Expense"), h("option", { value: "income" }, "Income"));
  const amount = h("input", { id: "amount_cents", name: "amount_cents", inputmode: "decimal", required: true, placeholder: "12.50" });
  const date = h("input", { id: "occurred_on", name: "occurred_on", type: "date", value: today(), required: true });
  const category = h("select", { id: "category_id", name: "category_id" });
  const source = h("select", { id: "income_source", name: "income_source" },
    h("option", { value: "allowance" }, "Allowance"), h("option", { value: "other" }, "Other income"));
  const note = h("input", { id: "note", name: "note", maxlength: "500" });
  const oneOff = h("input", { type: "checkbox", id: "one_off", name: "one_off" });
  const categoryField = field("Category", category, "Leave it on “Guess from the note” to let Float pick one.");
  const sourceField = field("Kind of income", source);
  const oneOffField = h("div", { class: "field" }, h("label", { class: "choice" }, oneOff, " One-off (not part of normal spending)"));
  const title = h("h2", {}, "Add a transaction");
  const save = h("button", { type: "submit", class: "button" }, "Save");
  const cancel = h("button", { type: "button", class: "button button-secondary", hidden: true, onclick: () => reset() }, "Cancel");
  const form = h("form", { class: "stack card txn-form", novalidate: true, id: "new" }, title,
    field("Type", kind), field("Amount (€)", amount), field("Date", date), categoryField, sourceField,
    field("Note", note), oneOffField, h("p", { class: "actions" }, save, cancel));
  const list = h("section", { class: "card", "aria-label": "Your transactions, newest first" });

  function toggle() {
    const income = kind.value === "income";
    categoryField.hidden = income;
    oneOffField.hidden = income;
    sourceField.hidden = !income;
  }
  kind.addEventListener("change", toggle);

  function reset() {
    editing = null;
    form.reset();
    date.value = today();
    title.textContent = "Add a transaction";
    cancel.hidden = true;
    kind.disabled = false;
    toggle();
  }

  function edit(item) {
    editing = item;
    kind.value = item.kind;
    kind.disabled = true;
    amount.value = (item.amount_cents / 100).toFixed(2);
    date.value = item.occurred_on;
    category.value = item.category_id ?? "";
    source.value = item.income_source === "other" ? "other" : "allowance";
    note.value = item.note;
    oneOff.checked = item.one_off;
    title.textContent = "Edit transaction";
    cancel.hidden = false;
    toggle();
    form.scrollIntoView({ behavior: "smooth" });
  }

  async function remove(item) {
    if (!confirm(`Delete the ${money(item.amount_cents)} ${item.kind} of ${item.occurred_on}?`)) return;
    try {
      await Api.personal("DELETE", `/transactions/${item.id}`, { version: item.version });
      await load();
    } catch (error) {
      alert(error.message);
    }
  }

  function describe(item) {
    if (item.kind === "expense") return categories.find((c) => c.id === item.category_id)?.name || "Settlement";
    return { allowance: "Allowance", settlement: "Settlement received" }[item.income_source] || "Other income";
  }

  async function load() {
    const items = await Api.personal("GET", "/transactions?limit=100");
    if (!items.length) {
      list.replaceChildren(h("p", {}, "No transactions yet. Add your first expense or income above."));
      return;
    }
    list.replaceChildren(h("ul", { class: "rows" }, items.map((item) => {
      const managed = item.origin !== "manual";
      return h("li", { class: "row" },
        h("span", { class: `row-icon ${item.kind === "income" ? "tone-green" : item.origin === "settlement" ? "tone-slate" : "tone-violet"}` },
          icon(item.kind === "income" ? "income" : item.origin === "settlement" ? "swap" : "cart")),
        h("span", { class: "row-main" },
          h("span", { class: "row-title" }, describe(item), item.one_off ? h("span", { class: "tag" }, "one-off") : null),
          h("span", { class: "row-meta" }, item.occurred_on, item.note ? ` · ${item.note}` : ""),
          managed ? h("span", { class: "row-meta" }, `Managed by its ${MANAGERS[item.origin] || item.origin}`) : null),
        h("span", { class: "row-side" },
          h("span", { class: `amount ${item.kind === "income" ? "amount-in" : "amount-out"}` },
            `${item.kind === "income" ? "+" : "−"}${money(item.amount_cents)}`),
          managed ? null : h("span", { class: "row-actions" },
            h("button", { type: "button", class: "link-button", onclick: () => edit(item) }, "Edit"),
            h("button", { type: "button", class: "link-button", onclick: () => remove(item) }, "Delete"))));
    })));
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const cents = parseMoney(amount.value);
    if (cents === null || cents === 0) {
      showProblem(form, { title: "Check your input", errors: { amount_cents: "Enter an amount like 12.50." } });
      return;
    }
    const income = kind.value === "income";
    const body = {
      kind: kind.value, amount_cents: cents, occurred_on: date.value, note: note.value.trim(),
      category_id: income || !category.value ? null : Number(category.value),
      income_source: income ? source.value : null, one_off: !income && oneOff.checked,
    };
    save.disabled = true;
    try {
      if (editing) await Api.personal("PATCH", `/transactions/${editing.id}`, { ...body, version: editing.version });
      else await Api.personal("POST", "/transactions", body, { headers: { "Idempotency-Key": crypto.randomUUID() } });
      reset();
      form.querySelector(".error-summary")?.remove();
      await load();
    } catch (error) {
      if (error.problem) showProblem(form, error.problem);
    } finally {
      save.disabled = false;
    }
  });

  categories = await Api.personal("GET", "/categories");
  category.replaceChildren(h("option", { value: "" }, "Guess from the note"),
    categories.map((c) => h("option", { value: String(c.id) }, c.name)));
  main.replaceChildren(h("div", { class: "page-head" }, h("h1", {}, "Transactions")), form, list);
  if (location.hash === "#income") kind.value = "income";
  toggle();
  await load();
})();
