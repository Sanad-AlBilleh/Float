// index.html: log in, or create an account. The personal service returns a signed token on success.
"use strict";

(() => {
  const { h, field, showProblem } = UI;
  const main = document.getElementById("content");

  async function signedIn(data) {
    Api.setToken(data.token);
    const me = await Api.personal("GET", "/me");
    location.replace(me.setup_complete ? "dashboard.html" : "setup.html");
  }

  function input(name, type, autocomplete) {
    return h("input", { id: name, name, type, autocomplete, required: true });
  }

  function form(mode) {
    const register = mode === "register";
    const fields = [
      field("Username", input("username", "text", "username"), register ? "3 to 32 lowercase letters, digits or _." : null),
      register ? field("Your name", input("display_name", "text", "name")) : null,
      field("Password", input("password", "password", register ? "new-password" : "current-password"),
        register ? "At least 12 characters." : null),
    ];
    const submit = h("button", { type: "submit", class: "button" }, register ? "Create account" : "Log in");
    const el = h("form", { class: "stack card", novalidate: true }, fields, submit);
    el.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      const body = Object.fromEntries(new FormData(el));
      try {
        await signedIn(await Api.personal("POST", register ? "/auth/register" : "/auth/login", body, { auth: false }));
      } catch (error) {
        if (error.problem) showProblem(el, error.problem);
      } finally {
        submit.disabled = false;
      }
    });
    return el;
  }

  function render(mode) {
    const register = mode === "register";
    UI.set(main, 
      h("h1", {}, register ? "Create your account" : "Log in"),
      form(mode),
      h("p", {}, register ? "Already have an account? " : "New here? ",
        h("a", { href: register ? "#login" : "#register" }, register ? "Log in" : "Create an account"), "."));
    main.querySelector("input")?.focus();
  }

  if (Api.token()) {
    location.replace("dashboard.html");
    return;
  }
  const show = () => render(location.hash === "#register" ? "register" : "login");
  window.addEventListener("hashchange", show);
  show();
})();
