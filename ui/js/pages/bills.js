// bills.html: recurring bills (FR-09–12). Paying a bill records the expense and links it, in one step.
"use strict";

(async () => {
  const { h, money, today, field, select, input, act, form, cents } = UI;
  const me = await Api.me();
  const main = UI.shell("Bills", me);
  const categories = await Api.personal("GET", "/categories");
  const name = (id) => categories.find((c) => c.id === id)?.name || "";
  const occurrences = h("section", { class: "card" });
  const seriesList = h("section", { class: "card" });

  const post = (o, verb, body = {}) => () => act(() => Api.personal("POST", `/occurrences/${o.id}/${verb}`, { version: o.version, ...body }), load);
  const button = (label, onclick) => h("button", { type: "button", class: "link-button", onclick }, label);

  function actions(o) {
    if (o.status === "paid") return button("Undo payment", post(o, "undo"));
    if (o.status === "skipped") return button("Unskip", post(o, "unskip"));
    return [button("Paid today", post(o, "pay", { paid_on: today() })), button("Skip", post(o, "skip"))];
  }

  function occurrenceRow(o) {
    return h("li", { class: "row" },
      h("span", { class: "row-main" },
        h("span", { class: "row-title" }, o.name, " ", h("span", { class: `status status-${o.status}` }, o.status)),
        h("span", { class: "row-meta" }, `Due ${o.due_date} · ${name(o.category_id)}`)),
      h("span", { class: "row-side" }, h("span", { class: "amount amount-out" }, money(o.amount_cents)),
        h("span", { class: "row-actions" }, actions(o))));
  }

  async function load() {
    const [rows, series] = await Promise.all([Api.personal("GET", "/occurrences"), Api.personal("GET", "/bills")]);
    UI.set(occurrences, h("div", { class: "card-head" }, h("h2", {}, "Upcoming and recent")),
      rows.length ? h("ul", { class: "rows" }, rows.map(occurrenceRow)) : h("p", { class: "muted" }, "No bills yet."));
    const active = series.filter((s) => !s.ended);
    UI.set(seriesList, h("div", { class: "card-head" }, h("h2", {}, "Your bills")),
      active.length ? h("ul", { class: "rows" }, active.map((s) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, s.name),
          h("span", { class: "row-meta" }, `${money(s.amount_cents)} · ${s.rule.freq === "once" ? "once" : `every ${s.rule.interval > 1 ? `${s.rule.interval} ` : ""}${s.rule.freq === "weekly" ? "week" : "month"}${s.rule.interval > 1 ? "s" : ""}`} from ${s.rule.anchor}`)),
        h("span", { class: "row-actions" }, h("button", { type: "button", class: "link-button",
          onclick: () => confirm(`End ${s.name}? Unpaid future dates are removed.`) && act(() => Api.personal("POST", `/bills/${s.id}/end`, { version: s.version }), load) }, "End")))))
        : h("p", { class: "muted" }, "No recurring bills."));
  }

  const add = form([h("h2", {}, "Add a bill"),
    field("Name", input("name", { maxlength: "100", required: true })),
    field("Amount (€)", input("amount_cents", { inputmode: "decimal", required: true })),
    field("Category", select("category_id", categories.map((c) => [c.id, c.name]), 4)),
    field("Repeats", select("freq", [["monthly", "Every month"], ["weekly", "Every week"], ["once", "Once"]], "monthly")),
    field("First due date", input("anchor_date", { type: "date", value: today() })),
    h("button", { type: "submit", class: "button" }, "Add bill")], async (data, el) => {
    await Api.personal("POST", "/bills", { name: String(data.get("name")).trim(), amount_cents: cents(data, "amount_cents"),
      category_id: Number(data.get("category_id")), freq: data.get("freq"), interval: 1, anchor_date: data.get("anchor_date") });
    el.reset();
    await load();
  });

  UI.set(main, h("div", { class: "page-head" }, h("h1", {}, "Bills")), occurrences, seriesList, add);
  await load();
})();
