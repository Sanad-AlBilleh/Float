// Shared page pieces: a safe element builder, money helpers, icons, the signed-in shell and messages.
// Everything the user typed is added with textContent (never innerHTML), so it cannot become HTML.
"use strict";

const UI = (() => {
  const ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
    receipt: '<path d="M5 3h14v18l-2.5-1.5L14 21l-2-1.5L10 21l-2.5-1.5L5 21z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    pie: '<path d="M21 12a9 9 0 1 1-9-9v9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2A5 5 0 0 1 21.5 19"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    wallet: '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 13.5h2"/>',
    income: '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/><path d="M4 21h16"/>',
    swap: '<path d="M7 4 3 8l4 4"/><path d="M3 8h14"/><path d="m17 12 4 4-4 4"/><path d="M21 16H7"/>',
    cart: '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M2 3h3l2.6 12.2a1 1 0 0 0 1 .8h9.5a1 1 0 0 0 1-.8L21 7H6"/>',
  };

  // The kept A1 pages (plan.md §6: activity, forecast, categories and account pages were trimmed).
  const NAV = [
    { href: "dashboard.html", label: "Dashboard", icon: "home" },
    { href: "transactions.html", label: "Transactions", icon: "list" },
    { href: "bills.html", label: "Bills", icon: "receipt" },
    { href: "goals.html", label: "Goals", icon: "target" },
    { href: "budgets.html", label: "Budgets", icon: "pie" },
    { href: "households.html", label: "Households", icon: "users" },
  ];

  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.innerHTML = ICONS[name] || ICONS.list; // constant markup from this file only
    return svg;
  }

  // h("p", {class: "muted"}, "text", child) builds an element; strings become text nodes.
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else if (key === "text") el.textContent = value;
      else el.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  const euro = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });

  function money(cents) {
    return euro.format(cents / 100);
  }

  // "12", "12.5" or "12,50" -> 1250 cents. Exact: no floating point, at most two decimals.
  function parseMoney(text) {
    const value = String(text || "").trim().replace(",", ".");
    if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
    const [whole, fraction = ""] = value.split(".");
    return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  }

  function today() {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }

  // A status line at the top of the page, for cold starts and for the other service being down.
  function banner(message, { tone = "notice", retry = false } = {}) {
    let box = document.getElementById("banner");
    if (!box) {
      box = h("div", { id: "banner", role: "status", "aria-live": "polite" });
      (document.querySelector("main") || document.body).prepend(box);
    }
    box.className = tone;
    box.replaceChildren(h("p", {}, message,
      retry ? h("button", { type: "button", class: "button button-small", onclick: () => location.reload() }, "Retry") : null));
  }

  function clearBanner() {
    document.getElementById("banner")?.remove();
  }

  // Field messages from a problem+json response, next to the form, plus a summary.
  function showProblem(form, problem) {
    form.querySelectorAll(".field-error").forEach((el) => el.remove());
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    form.querySelector(".error-summary")?.remove();
    const errors = problem.errors || {};
    const items = [];
    for (const [name, message] of Object.entries(errors)) {
      const input = form.querySelector(`[name="${CSS.escape(name)}"]`)
        || form.querySelector(`[data-field="${CSS.escape(name)}"]`);
      if (input) {
        input.setAttribute("aria-invalid", "true");
        input.closest(".field")?.append(h("p", { class: "field-error" }, message));
      }
      items.push(h("li", {}, message));
    }
    const summary = h("div", { class: "error-summary", role: "alert", tabindex: "-1" },
      h("p", {}, h("strong", {}, problem.title || "Something went wrong")),
      items.length ? h("ul", {}, items) : h("p", {}, problem.detail || "Please try again."));
    form.prepend(summary);
    summary.focus();
  }

  function field(label, input, hint) {
    return h("div", { class: "field" }, h("label", { for: input.id }, label), hint ? h("p", { class: "hint" }, hint) : null,
      input);
  }

  // The signed-in layout: sidebar on wide screens, tab bar on phones. Returns the <main> to fill.
  function shell(active, user) {
    const page = location.pathname.split("/").pop() || "dashboard.html";
    const link = (item) => h("a", {
      href: item.href, class: `nav-link${page === item.href ? " is-active" : ""}`,
      "aria-current": page === item.href ? "page" : null,
    }, icon(item.icon), h("span", {}, item.label));
    const initials = (user.display_name || "?").split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
    const logout = h("button", { type: "button", class: "icon-button", title: "Log out", onclick: () => Api.logout() },
      icon("logout"), h("span", { class: "visually-hidden" }, "Log out"));
    const main = h("main", { id: "content", class: "page" });
    document.body.className = "signed-in";
    document.body.replaceChildren(
      h("a", { class: "skip-link", href: "#content" }, "Skip to content"),
      h("div", { class: "shell" },
        h("aside", { class: "sidebar" },
          h("a", { class: "brand", href: "dashboard.html" }, h("span", { class: "brand-mark" }, icon("wallet")), h("span", {}, "Float")),
          h("nav", { "aria-label": "Main", class: "side-nav" }, h("p", { class: "nav-label" }, "Money"), NAV.slice(0, 5).map(link),
            h("p", { class: "nav-label" }, "Together"), NAV.slice(5).map(link)),
          h("div", { class: "sidebar-user" },
            h("span", { class: "user-chip" }, h("span", { class: "avatar" }, initials),
              h("span", { class: "user-text" }, h("strong", {}, user.display_name), h("small", {}, `@${user.username}`))),
            logout)),
        h("div", { class: "workspace" },
          h("header", { class: "topbar" },
            h("a", { class: "brand brand-mobile", href: "dashboard.html" }, h("span", { class: "brand-mark" }, icon("wallet")), h("span", {}, "Float")),
            h("p", { class: "topbar-hello" }, "Hello, ", h("strong", {}, user.display_name)),
            h("div", { class: "topbar-actions" },
              h("a", { class: "button button-small topbar-add", href: "transactions.html#new" }, icon("plus"), h("span", {}, "Add expense")))),
          main,
          h("footer", { class: "site-footer" }, h("p", {}, "Estimates depend on complete, accurate records. Float never connects to a bank."))),
        h("nav", { class: "tabbar", "aria-label": "Quick" }, [NAV[0], NAV[1], NAV[2], NAV[5]].map(link),
          h("button", { type: "button", class: "nav-link link-button", onclick: () => Api.logout() }, icon("logout"), h("span", {}, "Log out")))));
    document.title = `${active} · Float`;
    return main;
  }

  // Replace an element's content; null/false children are skipped (replaceChildren would print "null").
  function set(el, ...children) {
    el.replaceChildren(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
    return el;
  }

  // ``id`` defaults to the field name; pages with several forms pass a unique one.
  function select(name, options, value, id = name) {
    return h("select", { id, name }, options.map(([v, label]) => h("option", { value: String(v), selected: String(v) === String(value) || null }, label)));
  }

  function input(name, attrs = {}) {
    return h("input", { id: name, name, ...attrs });
  }

  // Run an action from a button; show the API's message in an alert if it is refused.
  async function act(action, after) {
    try {
      await action();
      if (after) await after();
    } catch (error) {
      if (error.status !== 503 || error.problem?.title !== "Starting up") alert(error.message);
    }
  }

  // A form whose submit handler gets the FormData; API problems are shown on the form.
  function form(children, onsubmit, attrs = {}) {
    const el = h("form", { class: "stack card", novalidate: true, ...attrs }, children);
    el.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = el.querySelector("button[type=submit]");
      if (button) button.disabled = true;
      try {
        el.querySelector(".error-summary")?.remove();
        await onsubmit(new FormData(el), el);
      } catch (error) {
        showProblem(el, error.problem || { title: "Check your input", detail: error.message });
      } finally {
        if (button) button.disabled = false;
      }
    });
    return el;
  }

  // Money typed in a form field, or a field error the form shows.
  function cents(data, name, { optional = false } = {}) {
    const text = String(data.get(name) || "").trim();
    if (optional && !text) return null;
    const value = parseMoney(text);
    if (value === null) {
      const error = new Error("Enter an amount like 12.50.");
      error.problem = { title: "Check your input", errors: { [name]: "Enter an amount like 12.50." } };
      throw error;
    }
    return value;
  }

  return { h, icon, money, parseMoney, today, banner, clearBanner, showProblem, field, shell, select, input, act, form, cents, set };
})();
