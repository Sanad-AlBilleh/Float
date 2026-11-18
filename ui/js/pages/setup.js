// setup.html: the one-time setup (FR-05): when tracking starts, the opening balance and the allowance.
"use strict";

(async () => {
  const { h, field, parseMoney, showProblem, today } = UI;
  const main = document.getElementById("content");
  const me = await Api.me();
  if (me.setup_complete) {
    location.replace("dashboard.html");
    return;
  }

  const firstOfMonth = `${today().slice(0, 8)}01`;
  const el = h("form", { class: "stack card", novalidate: true },
    field("Start tracking on", h("input", { id: "tracking_start", name: "tracking_start", type: "date", value: firstOfMonth, required: true }),
      "Money before this date is summed up in the opening balance."),
    field("Opening balance (€)", h("input", { id: "opening_balance_cents", name: "opening_balance_cents", inputmode: "decimal", value: "0" }),
      "What you had on that date, across your accounts."),
    field("Allowance day", h("input", { id: "allowance_day", name: "allowance_day", type: "number", min: "1", max: "31", value: "1" }),
      "The day of the month your allowance arrives."),
    field("Planned allowance (€)", h("input", { id: "planned_allowance_cents", name: "planned_allowance_cents", inputmode: "decimal", value: "750" }),
      "Expected each month. It never counts until you record it."),
    h("div", { class: "field" }, h("label", { class: "choice" },
      h("input", { type: "checkbox", name: "allowance_included", id: "allowance_included" }),
      " The opening balance already includes this cycle's allowance")),
    field("Monthly savings goal (€, optional)", h("input", { id: "monthly_savings_cents", name: "monthly_savings_cents", inputmode: "decimal", value: "0" })),
    h("button", { type: "submit", class: "button" }, "Start using Float"));

  el.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(el);
    const errors = {};
    const cents = {};
    for (const name of ["opening_balance_cents", "planned_allowance_cents", "monthly_savings_cents"]) {
      cents[name] = parseMoney(data.get(name));
      if (cents[name] === null) errors[name] = "Enter an amount like 12.50.";
    }
    if (Object.keys(errors).length) {
      showProblem(el, { title: "Check your input", errors });
      return;
    }
    try {
      await Api.personal("POST", "/setup", {
        tracking_start: data.get("tracking_start"), allowance_day: Number(data.get("allowance_day")),
        allowance_included: data.get("allowance_included") === "on", ...cents,
      });
      location.replace("dashboard.html");
    } catch (error) {
      if (error.problem) showProblem(el, error.problem);
    }
  });

  main.replaceChildren(h("h1", {}, `Welcome, ${me.display_name}`),
    h("p", { class: "lead" }, "Three numbers and Float can tell you how much is safe to spend each day."), el);
})();
