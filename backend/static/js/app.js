// Theme toggle + tiny UI helpers. No framework, no CDN.
(function () {
  const stored = localStorage.getItem("gn-theme");
  if (stored) document.documentElement.setAttribute("data-bs-theme", stored);

  window.gnToggleTheme = function () {
    const root = document.documentElement;
    const next = root.getAttribute("data-bs-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-bs-theme", next);
    localStorage.setItem("gn-theme", next);
  };

  document.addEventListener("htmx:responseError", function () {
    console.warn("dashboard refresh failed");
  });
})();
