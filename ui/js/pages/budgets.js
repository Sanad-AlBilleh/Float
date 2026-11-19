// budgets.html: spending per category this cycle against an optional limit (FR-16).
// Shares of shared expenses count here; their amounts come from the households service.
"use strict";

(async () => {
  const { h, money, field, input, form, cents } = UI;
  const me = await Api.me();
  const main = UI.shell("Budgets", me);
  const list = h("section", { class: "card" });

  async function load() {
    const rows = await Api.personal("GET", "/budgets");
    UI.set(list, h("ul", { class: "rows" }, rows.map((row) => {
      const limit = form([field(`Limit for ${row.category} (€, empty to clear)`,
        input(`limit_${row.category_id}`, { inputmode: "decimal", value: row.limit_cents === null ? "" : (row.limit_cents / 100).toFixed(2) })),
      h("button", { type: "submit", class: "button button-small button-secondary" }, "Save")], async (data) => {
        await Api.personal("PUT", `/budgets/${row.category_id}`, {
          limit_cents: cents(data, `limit_${row.category_id}`, { optional: true }), scope: "template" });
        await load();
      }, { class: "budget-form" });
      const percent = row.limit_cents ? Math.min(100, Math.round((row.consumption_cents * 100) / row.limit_cents)) : 0;
      return h("li", { class: "row budget-row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, row.category,
          row.state ? h("span", { class: `tag${row.state === "over" ? " tag-unusual" : ""}` }, row.state) : null),
          h("span", { class: "row-meta" }, `${money(row.consumption_cents)} spent`, row.limit_cents !== null ? ` of ${money(row.limit_cents)}` : ""),
          row.limit_cents ? h("div", { class: "progress-track" }, h("div", { class: `progress-fill${row.state === "over" ? " progress-over" : ""}`, style: `width: ${percent}%` })) : null),
        limit);
    })));
  }

  UI.set(main, h("div", { class: "page-head" }, h("h1", {}, "Budgets"),
    h("p", { class: "muted" }, "This cycle's spending per category. Your share of a shared expense counts, not what you fronted.")), list);
  await load();
})();
