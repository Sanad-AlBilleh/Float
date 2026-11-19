// household.html?id=N: one household (FR-17–26). Served by the households service. Recording an expense,
// paying a household bill or confirming a settlement also writes your ledger in the personal service; if
// that service is down, the households service answers "Ledger unavailable, nothing was saved", which the
// form shows. Reading the household keeps working, with names shown as "Member #id" if they are unknown.
"use strict";

(async () => {
  const { h, money, today, field, select, input, act, form, cents } = UI;
  const me = await Api.me({ cached: true });
  const main = UI.shell("Household", me);
  const id = Number(new URLSearchParams(location.search).get("id"));
  if (!id) {
    location.replace("households.html");
    return;
  }
  // The fixed categories (personal service migration 001), used when that service cannot be asked.
  const FIXED = ["Groceries", "Eating out", "Transport", "Housing", "Utilities", "Subscriptions", "Study", "Leisure",
    "Health", "Travel", "Other"].map((name, i) => ({ id: i + 1, name }));
  const categories = await Api.personal("GET", "/categories", undefined, { retry: false }).catch(() => FIXED);
  const sections = { members: h("section", { class: "card" }), expenses: h("section", { class: "card" }),
    balances: h("section", { class: "card" }), settlements: h("section", { class: "card" }), bills: h("section", { class: "card" }) };
  let page;
  const nameOf = (userId) => page.members.find((m) => m.user_id === userId)?.display_name || `Member #${userId}`;
  const active = () => page.members.filter((m) => m.status === "active");
  const everyone = () => active().map((m) => ({ user_id: m.user_id }));

  function members() {
    const owner = page.me.status === "active" && page.me.role === "owner" && !page.household.archived;
    const code = h("p", { class: "invite-code", role: "status" });
    UI.set(sections.members, h("div", { class: "card-head" }, h("h2", {}, "Members")),
      h("ul", { class: "rows" }, page.members.map((m) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, m.display_name, m.user_id === me.id ? " (you)" : ""),
          h("span", { class: "row-meta" }, m.role === "owner" ? "Owner" : "Member", m.status !== "active" ? ` · ${m.status}` : ""))))),
      owner ? h("p", { class: "actions" }, h("button", { type: "button", class: "button button-small", onclick: () => act(async () => {
        const invite = await Api.households("POST", `/households/${id}/invitations`);
        code.textContent = `Invitation code: ${invite.code} (works once, for ${invite.expires_in_hours} hours)`;
      }) }, "Invite someone"), code) : null,
      page.me.status === "active" && !owner ? h("p", {}, h("button", { type: "button", class: "link-button",
        onclick: () => confirm("Leave this household?") && act(() => Api.households("POST", `/households/${id}/leave`), () => { location.href = "households.html"; }) }, "Leave household")) : null);
  }

  async function expenses() {
    const rows = await Api.households("GET", `/households/${id}/expenses`);
    const add = page.me.status === "active" && !page.household.archived ? form([h("h3", {}, "Add a shared expense"),
      field("Description", input("description", { id: "e-description", maxlength: "100" })),
      field("Amount (€)", input("amount_cents", { id: "e-amount_cents", inputmode: "decimal" })),
      field("Date", input("spent_on", { id: "e-spent_on", type: "date", value: today() })),
      field("Category", select("category_id", categories.map((c) => [c.id, c.name]), 1, "e-category_id")),
      h("p", { class: "hint" }, "Split equally between every current member; you paid it."),
      h("button", { type: "submit", class: "button" }, "Add expense")], async (data, el) => {
      await Api.households("POST", `/households/${id}/expenses`, {
        description: String(data.get("description")).trim(), amount_cents: cents(data, "amount_cents"),
        spent_on: data.get("spent_on"), category_id: Number(data.get("category_id")), split_method: "equal",
        participants: everyone() }, { headers: { "Idempotency-Key": crypto.randomUUID() } });
      el.reset();
      await refresh();
    }) : null;
    UI.set(sections.expenses, h("div", { class: "card-head" }, h("h2", {}, "Shared expenses")),
      rows.length ? h("ul", { class: "rows" }, rows.map((e) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, e.description),
          h("span", { class: "row-meta" }, `${e.spent_on} · paid by ${nameOf(e.payer_user_id)} · `,
            Object.entries(e.shares).map(([user, share]) => `${nameOf(Number(user))} ${money(share)}`).join(", "))),
        h("span", { class: "row-side" }, h("span", { class: "amount" }, money(e.amount_cents)),
          e.payer_user_id === me.id ? h("span", { class: "row-actions" }, h("button", { type: "button", class: "link-button",
            onclick: () => confirm(`Delete ${e.description}?`) && act(() => Api.households("DELETE", `/households/${id}/expenses/${e.id}`, { version: e.version }), refresh) }, "Delete")) : null))))
        : h("p", { class: "muted" }, "No shared expenses yet."), add);
  }

  async function balances() {
    if (page.me.status !== "active") {
      UI.set(sections.balances, h("h2", {}, "Balances"), h("p", { class: "muted" }, "Current balances are for current members."));
      return;
    }
    const data = await Api.households("GET", `/households/${id}/balances`);
    UI.set(sections.balances, h("div", { class: "card-head" }, h("h2", {}, "Balances")),
      h("ul", { class: "rows" }, data.nets.map((n) => h("li", { class: "row" }, h("span", { class: "row-main" }, n.display_name),
        h("span", { class: `amount ${n.net_cents >= 0 ? "amount-in" : "amount-out"}` },
        n.net_cents === 0 ? "settled" : n.net_cents > 0 ? `is owed ${money(n.net_cents)}` : `owes ${money(-n.net_cents)}`)))),
      data.plan.length ? h("div", {}, h("h3", {}, "To settle up"), h("ul", {}, data.plan.map((t) => h("li", {}, `${nameOf(t.from_user)} pays ${nameOf(t.to_user)} ${money(t.amount_cents)}`))))
        : h("p", { class: "muted" }, "Everyone is settled."));
  }

  async function settlements() {
    const rows = await Api.households("GET", `/households/${id}/settlements`);
    const others = active().filter((m) => m.user_id !== me.id);
    const record = page.me.status === "active" && others.length ? form([h("h3", {}, "Record a payment made outside Float"),
      field("I paid", select("payee", others.map((m) => [m.user_id, m.display_name]), null, "s-payee")),
      field("Amount (€)", input("amount_cents", { id: "s-amount_cents", inputmode: "decimal" })),
      field("Paid on", input("paid_on", { id: "s-paid_on", type: "date", value: today() })),
      h("p", { class: "hint" }, "Nothing changes until they confirm it."),
      h("button", { type: "submit", class: "button" }, "Record")], async (data, el) => {
      await Api.households("POST", `/households/${id}/settlements`, { payer_user_id: me.id, payee_user_id: Number(data.get("payee")),
        amount_cents: cents(data, "amount_cents"), paid_on: data.get("paid_on") }, { headers: { "Idempotency-Key": crypto.randomUUID() } });
      el.reset();
      await refresh();
    }) : null;
    const action = (s, verb, body = {}) => () => act(() => Api.households("POST", `/settlements/${s.id}/${verb}`, { version: s.version, ...body }), refresh);
    UI.set(sections.settlements, h("div", { class: "card-head" }, h("h2", {}, "Settlements")),
      rows.length ? h("ul", { class: "rows" }, rows.map((s) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, `${nameOf(s.payer_user_id)} → ${nameOf(s.payee_user_id)}`, " ",
          h("span", { class: "tag" }, s.status)), h("span", { class: "row-meta" }, `${s.paid_on}${s.reason ? ` · ${s.reason}` : ""}`)),
        h("span", { class: "row-side" }, h("span", { class: "amount" }, money(s.amount_cents)),
          s.status === "pending" ? h("span", { class: "row-actions" }, s.initiated_by === me.id
            ? h("button", { type: "button", class: "link-button", onclick: action(s, "cancel") }, "Cancel")
            : [s.payer_user_id === me.id || s.payee_user_id === me.id
              ? h("button", { type: "button", class: "link-button", onclick: action(s, "confirm") }, "Confirm") : null,
            s.payer_user_id === me.id || s.payee_user_id === me.id
              ? h("button", { type: "button", class: "link-button", onclick: () => { const reason = prompt("Why are you rejecting it?") ?? ""; action(s, "reject", { reason: reason.slice(0, 200) })(); } }, "Reject") : null]) : null))))
        : h("p", { class: "muted" }, "No settlements yet."), record);
  }

  async function bills() {
    const view = await Api.households("GET", `/households/${id}/bills`);
    const owner = page.me.status === "active" && page.me.role === "owner" && !page.household.archived;
    const add = owner ? form([h("h3", {}, "Add a household bill"), field("Name", input("name", { id: "b-name", maxlength: "100" })),
      field("Amount (€)", input("amount_cents", { id: "b-amount_cents", inputmode: "decimal" })),
      field("Category", select("category_id", categories.map((c) => [c.id, c.name]), 5, "b-category_id")),
      field("First due date", input("anchor_date", { id: "b-anchor_date", type: "date", value: today() })),
      h("p", { class: "hint" }, "Monthly, split equally between every current member."),
      h("button", { type: "submit", class: "button" }, "Add bill")], async (data, el) => {
      await Api.households("POST", `/households/${id}/bills`, { name: String(data.get("name")).trim(), amount_cents: cents(data, "amount_cents"),
        category_id: Number(data.get("category_id")), freq: "monthly", interval: 1, anchor_date: data.get("anchor_date"),
        split_method: "equal", participants: everyone() });
      el.reset();
      await refresh();
    }) : null;
    UI.set(sections.bills, h("div", { class: "card-head" }, h("h2", {}, "Household bills")),
      view.cycle_estimated ? h("p", { class: "warning" }, "Your allowance cycle is unavailable right now, so a calendar month is used.") : null,
      view.occurrences.length ? h("ul", { class: "rows" }, view.occurrences.map((o) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title" }, o.name, " ", h("span", { class: `status status-${o.status}` }, o.status)),
          h("span", { class: "row-meta" }, `Due ${o.due_date}`, o.participant ? ` · your share ${money(o.my_share_cents)}` : " · not shared with you",
            o.payer_user_id ? ` · paid by ${nameOf(o.payer_user_id)}` : "")),
        h("span", { class: "row-side" }, h("span", { class: "amount" }, money(o.amount_cents)),
          o.participant && page.me.status === "active" ? h("span", { class: "row-actions" },
            o.status === "paid"
              ? (o.payer_user_id === me.id ? h("button", { type: "button", class: "link-button", onclick: () => act(() => Api.households("POST", `/household-occurrences/${o.id}/undo`, { version: o.version }), refresh) }, "Undo payment") : null)
              : o.status === "skipped"
                ? h("button", { type: "button", class: "link-button", onclick: () => act(() => Api.households("POST", `/household-occurrences/${o.id}/unskip`, { version: o.version }), refresh) }, "Unskip")
                : [h("button", { type: "button", class: "link-button", onclick: () => act(() => Api.households("POST", `/household-occurrences/${o.id}/pay`, { version: o.version, paid_on: today() }), refresh) }, "I paid it today"),
                  h("button", { type: "button", class: "link-button", onclick: () => act(() => Api.households("POST", `/household-occurrences/${o.id}/skip`, { version: o.version }), refresh) }, "Skip")]) : null))))
        : h("p", { class: "muted" }, "No household bills."), add);
  }

  async function refresh() {
    page = await Api.households("GET", `/households/${id}`);
    document.title = `${page.household.name} · Float`;
    UI.set(main, h("div", { class: "page-head" }, h("h1", {}, page.household.name),
      page.household.archived ? h("p", { class: "muted" }, "Archived: read only.") : null),
    sections.members, sections.balances, sections.expenses, sections.settlements, sections.bills);
    members();
    await Promise.all([expenses(), balances(), settlements(), bills()]);
  }

  try {
    await refresh();
  } catch (error) {
    UI.set(main, h("div", { class: "warning", role: "alert" }, h("p", {}, error.status === 404 ? "No such household." : error.message)),
      h("p", {}, h("a", { href: "households.html" }, "Back to households")));
  }
})();
