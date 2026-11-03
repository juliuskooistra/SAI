/*
  app.js: the start of the frontend. Sign-in state, the menu and the pages.

  Pages are "hash routes": the part of the address after "#", like
  #/catalogue or #/bike/12. That part never reaches the server, so changing
  page doesn't load anything from it; this file just swaps what's in <main>.

  - Not signed in: every route shows the sign-in page (#/login).
  - The menu shows the staff pages only for role "staff". Opening a staff
    page by hand as a customer shows "This page is for shop staff only."
    (Hiding pages is not access control: the API refuses /staff calls from
    customers anyway, with 403.)
*/

import * as api from "./api.js";
import { el, show, takeFlash, setFlash, message } from "./ui.js";

import * as loginPage from "./pages/login.js";
import * as cataloguePage from "./pages/catalogue.js";
import * as bikePage from "./pages/bike.js";
import * as myPage from "./pages/my.js";
import * as accountPage from "./pages/account.js";
import * as assistantPage from "./pages/assistant.js";
import * as boardPage from "./pages/staff-board.js";
import * as inventoryPage from "./pages/staff-inventory.js";
import * as pricesPage from "./pages/staff-prices.js";
import * as ordersPage from "./pages/staff-orders.js";
import * as analyticsPage from "./pages/staff-analytics.js";
import * as jobsPage from "./pages/staff-jobs.js";

// Every page: its route, its title in the menu, and who may see it.
const ROUTES = [
  { path: "catalogue", title: "Catalogue", page: cataloguePage, menu: true },
  { path: "bike", title: "Bike", page: bikePage },              // #/bike/<id>
  { path: "my", title: "My rentals and orders", page: myPage, menu: true },
  { path: "assistant", title: "Assistant", page: assistantPage, menu: true },
  { path: "account", title: "Account", page: accountPage, menu: true },
  { path: "staff/board", title: "Today's board", page: boardPage, menu: true, staff: true },
  { path: "staff/inventory", title: "Inventory", page: inventoryPage, menu: true, staff: true },
  { path: "staff/prices", title: "Prices", page: pricesPage, menu: true, staff: true },
  { path: "staff/orders", title: "Orders", page: ordersPage, menu: true, staff: true },
  { path: "staff/analytics", title: "Analytics", page: analyticsPage, menu: true, staff: true },
  { path: "staff/jobs", title: "Jobs", page: jobsPage, menu: true, staff: true },
];

/** "#/bike/12?start=…" -> { path: "bike", id: "12", query: URLSearchParams } */
function parseHash() {
  const [route, queryText] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = route.split("/").filter(Boolean);
  if (parts[0] === "bike") return { path: "bike", id: parts[1], query: new URLSearchParams(queryText) };
  return { path: parts.join("/") || "catalogue", id: null, query: new URLSearchParams(queryText) };
}

/** The header: menu links (staff links for staff only), the user and Log out. */
function drawHeader(session, currentPath) {
  const menu = document.getElementById("menu");
  const userBox = document.getElementById("user-box");
  if (!session) {
    menu.replaceChildren();
    userBox.replaceChildren();
    return;
  }
  const isStaff = session.role === "staff";
  const link = (route) => el("a", {
    href: `#/${route.path}`,
    class: route.path === currentPath ? "active" : null,
    "aria-current": route.path === currentPath ? "page" : null,
  }, route.title);

  show(menu,
    ROUTES.filter((r) => r.menu && !r.staff).map(link),
    isStaff ? el("span", { class: "menu-group" }, "Staff:") : null,
    isStaff ? ROUTES.filter((r) => r.menu && r.staff).map(link) : null);

  show(userBox,
    el("span", {}, `${session.username} (${session.role})`),
    el("button", { type: "button", onclick: logOut }, "Log out"));
}

async function logOut(event) {
  event.target.disabled = true;
  try {
    await api.signOut();   // revokes this tab's API key
  } catch {
    // The key may have expired already; we sign out here either way.
  }
  location.hash = "#/login";
  render();   // in case we were on #/login already
}

/** Show the page for the current address. Called on every hash change. */
async function render() {
  const session = api.getSession();
  const { path, id, query } = parseHash();
  const main = document.getElementById("main");

  // Not signed in: only the sign-in page. Signed in: no sign-in page.
  if (!session && path !== "login") { location.hash = "#/login"; return; }
  if (session && path === "login") { location.hash = "#/catalogue"; return; }

  drawHeader(session, path);

  // Each page draws into its own fresh <section>. If the user moves on
  // before a page has finished loading, its late answers land in a section
  // that is no longer on screen and do no harm.
  const view = el("section", {});
  show(main, view);
  const flash = takeFlash();

  if (path === "login") {
    document.title = "Sign in · BikeShop";
    return loginPage.render(view, { flash, onSignedIn: () => { location.hash = "#/catalogue"; } });
  }

  const route = ROUTES.find((r) => r.path === path);
  if (!route) {
    show(view, el("h1", {}, "Page not found"), el("p", {}, el("a", { href: "#/catalogue" }, "Go to the catalogue")));
    return;
  }
  document.title = `${route.title} · BikeShop`;
  if (route.staff && session.role !== "staff") {
    show(view, el("h1", {}, route.title), message("error", "This page is for shop staff only."));
    return;
  }
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
  try {
    await route.page.render(view, { id, query, session, flash });
  } catch (error) {
    // A page that fails to load shows the reason instead of staying blank.
    console.error(error);
    view.append(message("error", error.message || "Something went wrong on this page."));
  }
}

// A 401 from the API (key expired or revoked): back to the sign-in page.
api.onUnauthorized((detail) => {
  setFlash("info", detail);   // the API says why, e.g. "Invalid or expired API key. Sign in again …"
  if (location.hash === "#/login") render();
  else location.hash = "#/login";
});

window.addEventListener("hashchange", render);
render();
