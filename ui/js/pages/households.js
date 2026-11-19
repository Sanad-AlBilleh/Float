// households.html: the households you belong to, create one, or join with an invitation code (FR-17–18).
// Everything here comes from the households service.
"use strict";

(async () => {
  const { h, field, input, form } = UI;
  const me = await Api.me({ cached: true });
  const main = UI.shell("Households", me);
  const list = h("section", { class: "card" });

  async function load() {
    const households = await Api.households("GET", "/households");
    UI.set(list, h("div", { class: "card-head" }, h("h2", {}, "Your households")),
      households.length ? h("ul", { class: "rows" }, households.map((x) => h("li", { class: "row" },
        h("span", { class: "row-main" }, h("a", { class: "row-title", href: `household.html?id=${x.id}` }, x.name),
          h("span", { class: "row-meta" }, x.archived ? "Archived" : x.active_member ? "Member" : "Former member")))))
        : h("p", { class: "muted" }, "You are not in a household yet."));
  }

  const create = form([h("h2", {}, "Create a household"), field("Name", input("name", { maxlength: "60" })),
    h("button", { type: "submit", class: "button" }, "Create")], async (data) => {
    const created = await Api.households("POST", "/households", { name: String(data.get("name")).trim() });
    location.href = `household.html?id=${created.id}`;
  });
  const join = form([h("h2", {}, "Join with a code"), field("Invitation code", input("code", { autocomplete: "off" }), "Ask the owner for one; it works once, for 72 hours."),
    h("button", { type: "submit", class: "button" }, "Join")], async (data) => {
    const joined = await Api.households("POST", "/households/join", { code: String(data.get("code")).trim() });
    location.href = `household.html?id=${joined.id}`;
  });

  UI.set(main, h("div", { class: "page-head" }, h("h1", {}, "Households")), list, h("div", { class: "cards" }, create, join));
  await load();
})();
