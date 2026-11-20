// dashboard.html: safe-to-spend and how it was worked out (FR-27–29), alerts, and "can I afford it?".
// Household terms come from the households service through the personal service; when it is down the
// dashboard still loads and says so (Assignment 2 §3).
"use strict";

(async () => {
  const { h, icon, money, parseMoney } = UI;
  const me = await Api.me();
  const main = UI.shell("Dashboard", me);
  const days = (n) => `${n} day${n === 1 ? "" : "s"}`;

  let view;
  let alerts = [];
  try {
    [view, alerts] = await Promise.all([Api.personal("GET", "/dashboard"),
      Api.personal("GET", "/alerts").catch(() => [])]);
  } catch (error) {
    UI.set(main, h("div", { class: "warning", role: "alert" }, h("p", {}, error.message)));
    return;
  }
  const t = view.terms;
  const warnings = [];
  if (!view.households_available) {
    warnings.push(h("div", { class: "warning", role: "status" }, h("p", {},
      h("strong", {}, "Household balances are unavailable right now. "),
      "Safe-to-spend below leaves out your flat's bills and what you owe flatmates until the households service answers again.")));
  }
  if (view.shortfall_cents) {
    warnings.push(h("div", { class: "warning warning-strong", role: "alert" }, h("p", {},
      h("strong", {}, `Shortfall: ${money(view.shortfall_cents)}. `),
      "Your bills and protected savings add up to more than your recorded balance.")));
  }
  if (view.terms.recorded_balance_cents < 0) {
    warnings.push(h("div", { class: "warning", role: "alert" }, h("p", {},
      h("strong", {}, `Your recorded balance is below zero (${money(t.recorded_balance_cents)}).`))));
  }
  if (view.allowance_reminder) {
    warnings.push(h("div", { class: "warning", role: "status" }, h("p", {},
      h("strong", {}, "No allowance recorded this cycle. "), `If your ${money(view.planned_allowance_cents)} has arrived, `,
      h("a", { href: "transactions.html#income" }, "record it as income"), ". Float never assumes it arrived.")));
  }

  const row = (label, cents, sign = "−") => h("tr", {}, h("th", { scope: "row" }, `${sign} ${label}`),
    h("td", { class: "num" }, money(cents)));
  const breakdown = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "How Float worked it out")),
    h("div", { class: "table-scroll" }, h("table", { class: "table breakdown" }, h("tbody", {},
      row("Recorded balance", t.recorded_balance_cents, ""),
      row(`Bills due before ${view.next_allowance}`, t.personal_bills_cents),
      row(view.in_household ? "Household bill shares" : "Household bill shares (no household yet)", t.household_bill_shares_cents),
      row("Protected savings", t.protected_savings_cents),
      row(view.in_household ? "What you owe flatmates" : "What you owe flatmates (no household yet)", t.household_payables_cents),
      row("Goal plan reserve", t.goal_plan_reserve_cents),
      h("tr", { class: "total" }, h("th", { scope: "row" }, "= Discretionary"),
        h("td", { class: "num" }, money(view.discretionary_cents)))))),
    h("p", { class: "muted" }, `Your planned allowance of ${money(view.planned_allowance_cents)} is expected, not counted, until you record it.`,
      view.household_receivables_cents ? ` Flatmates owe you ${money(view.household_receivables_cents)}; it counts once they settle up.` : ""));

  const result = h("div", { role: "status" });
  const cost = h("input", { id: "cost", name: "cost", inputmode: "decimal", placeholder: "e.g. 35" });
  const preview = h("form", { class: "preview-form" }, UI.field("Total cost (€)", cost, "A purchase or trip. Nothing is saved."),
    h("button", { type: "submit", class: "button" }, "Preview"));
  preview.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (parseMoney(cost.value) === null) {
      UI.set(result, h("p", { class: "field-error" }, "Enter an amount like 35 or 12.50."));
      return;
    }
    const p = await Api.personal("GET", `/dashboard/preview?cost=${encodeURIComponent(cost.value)}`);
    result.className = "notice preview-result";
    UI.set(result, h("p", {}, p.after_shortfall_cents
      ? `You would be ${money(p.after_shortfall_cents)} short.`
      : `Afterwards you could spend ${money(p.after_daily_cents)} a day.`));
  });

  const unread = alerts.filter((a) => !a.read);
  UI.set(main, 
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, `Today, ${view.today}`),
      h("p", { class: "muted" }, "Your money at a glance, until your next allowance."))),
    ...warnings,
    h("div", { class: "dash" },
      h("div", { class: "dash-col" },
        h("section", { class: "hero" }, h("h2", {}, "Safe to spend today"),
          h("p", { class: "figure figure-large" }, money(view.daily_cents), " ", h("span", { class: "hero-unit" }, "per day")),
          h("p", {}, `${money(view.discretionary_cents)} to last ${days(view.days_remaining)}, until your next allowance on ${view.next_allowance}.`),
          h("p", { class: "actions" }, h("span", { class: "pill" }, icon("calendar"), `${days(view.days_remaining)} left`),
            view.household_receivables_cents ? h("span", { class: "pill" }, icon("users"), `Owed to you ${money(view.household_receivables_cents)}`) : null)),
        h("section", { class: "cards" },
          h("div", { class: "card stat" }, h("span", { class: "stat-icon" }, icon("wallet")), h("h2", { class: "stat-label" }, "Recorded balance"),
            h("p", { class: "figure" }, money(t.recorded_balance_cents))),
          h("div", { class: "card stat" }, h("span", { class: "stat-icon tone-teal" }, icon("calendar")), h("h2", { class: "stat-label" }, "Next allowance"),
            h("p", { class: "figure" }, view.next_allowance),
            h("p", { class: "muted" }, `Expected ${money(view.planned_allowance_cents)}, not counted until you record it.`))),
        breakdown),
      h("div", { class: "dash-col" },
        unread.length ? h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, `${unread.length} new alert${unread.length === 1 ? "" : "s"}`)),
          h("ul", { class: "rows" }, unread.slice(0, 5).map((a) => h("li", { class: "row" },
            h("span", { class: `row-icon ${a.severity === "critical" ? "tone-red" : a.severity === "warning" ? "tone-amber" : "tone-blue"}` }, icon("bell")),
            h("span", { class: "row-main" }, h("span", { class: "row-meta" }, a.message)))))) : null,
        h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Can I afford it?")), preview, result))));
})();
