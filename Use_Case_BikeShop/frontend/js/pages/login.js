/*
  Sign in / create an account (#/login).

  Sign in: POST /auth/generate-key with username and password gives this
  browser tab its own API key ("web-xxxxxxxx", valid 1 day). api.js keeps it
  in sessionStorage. Create an account: POST /auth/register, then sign in.
*/

import * as api from "../api.js";
import { el, show, run, message } from "../ui.js";

export function render(view, { flash, onSignedIn }) {
  const errorArea = el("div", {});

  // --- sign in ---
  const username = el("input", { name: "username", autocomplete: "username", required: true });
  const password = el("input", { name: "password", type: "password", autocomplete: "current-password", required: true });
  const signInButton = el("button", { type: "submit", class: "primary" }, "Sign in");
  const signInForm = el("form", { class: "narrow", "aria-label": "Sign in" },
    el("label", {}, "Username", username),
    el("label", {}, "Password", password),
    el("div", {}, signInButton));
  signInForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const answer = await run(signInButton, errorArea, () => api.signIn(username.value.trim(), password.value));
    if (answer) onSignedIn();
  });

  // --- create an account ---
  const newUsername = el("input", { name: "new-username", autocomplete: "username", required: true });
  const email = el("input", { name: "email", type: "email", autocomplete: "email", required: true });
  const newPassword = el("input", { name: "new-password", type: "password", autocomplete: "new-password", minlength: 10, required: true });
  const registerButton = el("button", { type: "submit", class: "primary" }, "Create account");
  const registerForm = el("form", { class: "narrow", "aria-label": "Create an account", hidden: true },
    el("label", {}, "Username", newUsername),
    el("label", {}, "Email", email),
    el("label", {}, "Password (at least 10 characters)", newPassword),
    el("div", {}, registerButton));
  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (newPassword.value.length < 10) {
      show(errorArea, message("error", "The password needs at least 10 characters."));
      return;
    }
    const answer = await run(registerButton, errorArea, async () => {
      await api.register(newUsername.value.trim(), email.value.trim(), newPassword.value);
      return api.signIn(newUsername.value.trim(), newPassword.value);
    });
    if (answer) onSignedIn();
  });

  // --- two tabs: Sign in | Create an account ---
  const tabButton = (label, form) => el("button", {
    type: "button", role: "tab", onclick: () => {
      signInForm.hidden = form !== signInForm;
      registerForm.hidden = form !== registerForm;
      for (const b of tabs.children) b.setAttribute("aria-selected", String(b.textContent === label));
      errorArea.replaceChildren();
    },
  }, label);
  const tabs = el("div", { class: "tabs", role: "tablist" },
    tabButton("Sign in", signInForm), tabButton("Create an account", registerForm));
  tabs.firstChild.setAttribute("aria-selected", "true");

  show(view,
    el("h1", {}, "Welcome to BikeShop"),
    el("p", {}, "Buy a bike, or rent one by the hour or the day."),
    flash,
    tabs, errorArea, signInForm, registerForm);
  username.focus();
}
