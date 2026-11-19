// goals.html: savings goals, protected money and the plan per cycle (FR-13–15).
"use strict";

(async () => {
  const { h, money, field, select, input, act, form, cents } = UI;
  const me = await Api.me();
  const main = UI.shell("Goals", me);
  const list = h("div", { class: "goal-grid" });
  const STATUS = { complete: "Complete", no_target_date: "No target date", overdue: "Overdue", on_plan: "On plan", behind: "Behind" };

  async function load() {
    const goals = await Api.personal("GET", "/goals");
    UI.set(list, ...(goals.length ? goals.map((g) => {
      const percent = Math.min(100, Math.round((g.protected_cents * 100) / g.target_cents));
      const move = form([field("Amount (€)", input(`delta_${g.id}`, { inputmode: "decimal" })),
        h("p", { class: "actions" }, h("button", { type: "submit", class: "button button-small", name: "action", value: "protect" }, "Protect"),
          h("button", { type: "submit", class: "button button-small button-secondary", name: "action", value: "release" }, "Release"))],
      async (data, el) => {
        const amount = cents(data, `delta_${g.id}`);
        const sign = el.dataset.action === "release" ? -1 : 1;
        await Api.personal("POST", `/goals/${g.id}/movements`, { delta_cents: sign * amount });
        await load();
      }, { class: "stack" });
      move.querySelectorAll("button[name=action]").forEach((b) => b.addEventListener("click", () => { move.dataset.action = b.value; }));
      return h("section", { class: "card goal" },
        h("div", { class: "goal-top" }, h("h2", {}, g.name), h("span", { class: "pill" }, STATUS[g.plan.status] || g.plan.status)),
        h("p", {}, `${money(g.protected_cents)} of ${money(g.target_cents)}`, g.target_date ? ` by ${g.target_date}` : ""),
        h("div", { class: "progress-track" }, h("div", { class: "progress-fill", style: `width: ${percent}%` })),
        g.plan.planned_cents ? h("p", { class: "muted" }, `This cycle's plan: ${money(g.plan.planned_cents)}`,
          g.auto_reserve ? " (held back from safe-to-spend automatically)." : ".") : null,
        move,
        h("p", { class: "goal-actions" }, h("button", { type: "button", class: "link-button",
          onclick: () => confirm(`Archive ${g.name}? Its protected money is released.`) && act(() => Api.personal("POST", `/goals/${g.id}/archive`, { version: g.version }), load) }, "Archive")));
    }) : [h("p", { class: "muted" }, "No goals yet.")]));
  }

  const add = form([h("h2", {}, "New goal"),
    field("Name", input("name", { maxlength: "100" })),
    field("Target (€)", input("target_cents", { inputmode: "decimal" })),
    field("Target date (optional)", input("target_date", { type: "date" })),
    field("Priority", select("priority", [[1, "High"], [2, "Normal"], [3, "Low"]], 2)),
    h("div", { class: "field" }, h("label", { class: "choice" }, input("auto_reserve", { type: "checkbox" }),
      " Hold this cycle's plan back from safe-to-spend automatically")),
    h("button", { type: "submit", class: "button" }, "Add goal")], async (data, el) => {
    await Api.personal("POST", "/goals", { name: String(data.get("name")).trim(), target_cents: cents(data, "target_cents"),
      target_date: data.get("target_date") || null, priority: Number(data.get("priority")),
      auto_reserve: data.get("auto_reserve") === "on" });
    el.reset();
    await load();
  });

  UI.set(main, h("div", { class: "page-head" }, h("h1", {}, "Goals")), list, add);
  await load();
})();
