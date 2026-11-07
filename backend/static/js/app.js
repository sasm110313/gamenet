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

  // Cloud management: show only tariffs/groups belonging to the chosen edge.
  function filterOptions(select, attribute, value) {
    let selectedStillValid = false;
    Array.from(select.options).forEach(function (option) {
      if (!option.value) return;
      const matches = option.getAttribute(attribute) === value;
      option.hidden = !matches;
      option.disabled = !matches;
      if (matches && option.selected) selectedStillValid = true;
    });
    if (!selectedStillValid) select.value = "";
  }

  function syncEdgeOptions(edgeSelect) {
    const form = edgeSelect.form;
    if (!form) return;
    const targets = form.querySelectorAll(
      "[data-gn-edge-tariff-select],[data-gn-edge-group-select]"
    );
    targets.forEach(function (select) {
      const attribute = select.hasAttribute("data-gn-edge-tariff-select")
        ? "data-edge"
        : "data-edge";
      filterOptions(select, attribute, edgeSelect.value);
    });
  }

  function wireEdgeSelects() {
    document.querySelectorAll("[data-gn-edge-select]").forEach(function (select) {
      select.addEventListener("change", function () { syncEdgeOptions(select); });
      syncEdgeOptions(select);
    });
  }

  // Session start: show only the selected customer's personal rates.
  function syncRateOptions(customerSelect) {
    const form = customerSelect.form;
    if (!form) return;
    const rateSelect = form.querySelector("[data-gn-rate-select]");
    if (!rateSelect) return;
    const customerId = customerSelect.value;
    let selectedStillValid = false;
    Array.from(rateSelect.options).forEach(function (option) {
      if (!option.value) return; // fallback "default / group" is always offered
      const owner = option.getAttribute("data-customer");
      const matches = owner === customerId;
      option.hidden = !matches;
      option.disabled = !matches;
      if (matches && option.selected) selectedStillValid = true;
    });
    if (!selectedStillValid) rateSelect.value = "";
  }

  function wireRateSelects() {
    document.querySelectorAll("[data-gn-customer-select]").forEach(function (select) {
      select.addEventListener("change", function () { syncRateOptions(select); });
      syncRateOptions(select);
    });
  }

  function wireAll() {
    wireRateSelects();
    wireEdgeSelects();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireAll);
  } else {
    wireAll();
  }
})();
