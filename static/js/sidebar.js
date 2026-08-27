(function () {
  var sidebar = document.getElementById("sidebar");
  var btn = document.getElementById("collapseBtn");
  var overlay = document.getElementById("sidebarOverlay");
  if (!sidebar || !btn) return;

  var MOBILE_BREAKPOINT = 900;
  var STORAGE_KEY = "fnrg_sidebar_collapsed";

  function isMobile() {
    return window.innerWidth <= MOBILE_BREAKPOINT;
  }

  // --- Desktop: persistent icon-only collapse ---
  function applyDesktopState(collapsed) {
    sidebar.classList.toggle("collapsed", collapsed);
  }

  var savedCollapsed = localStorage.getItem(STORAGE_KEY) === "1";
  if (!isMobile()) {
    applyDesktopState(savedCollapsed);
  }

  // --- Mobile: off-canvas drawer with backdrop ---
  function openMobileDrawer() {
    sidebar.classList.add("mobile-open");
    if (overlay) overlay.classList.add("visible");
    document.body.classList.add("no-scroll");
  }

  function closeMobileDrawer() {
    sidebar.classList.remove("mobile-open");
    if (overlay) overlay.classList.remove("visible");
    document.body.classList.remove("no-scroll");
  }

  btn.addEventListener("click", function () {
    if (isMobile()) {
      if (sidebar.classList.contains("mobile-open")) {
        closeMobileDrawer();
      } else {
        openMobileDrawer();
      }
    } else {
      var collapsed = !sidebar.classList.contains("collapsed");
      applyDesktopState(collapsed);
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    }
  });

  if (overlay) {
    overlay.addEventListener("click", closeMobileDrawer);
  }

  // Close the mobile drawer whenever a nav link is tapped, so navigating
  // doesn't leave the drawer open behind the new page.
  sidebar.querySelectorAll(".nav-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (isMobile()) closeMobileDrawer();
    });
  });

  // Keep behavior sane across resizes (e.g. rotating a tablet, or
  // resizing a desktop window past the breakpoint).
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (isMobile()) {
        applyDesktopState(false); // don't show the icon-only rail on mobile
      } else {
        closeMobileDrawer();
        applyDesktopState(localStorage.getItem(STORAGE_KEY) === "1");
      }
    }, 150);
  });
})();
