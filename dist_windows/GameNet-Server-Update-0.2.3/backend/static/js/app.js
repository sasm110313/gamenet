// Rahro Unified Design System — Locked Light Chalk & Sand-Navy Theme.
(function () {
  try {
    localStorage.removeItem("gn-theme");
    localStorage.removeItem("tablerTheme");
  } catch (e) {}
  document.documentElement.setAttribute("data-bs-theme", "light");

  window.gnToggleTheme = function () {
    document.documentElement.setAttribute("data-bs-theme", "light");
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

  // -------------------------------------------------------------------------
  // Catalog JSON loader (#gnCatalogData[data-json]) & Format Helpers
  // -------------------------------------------------------------------------
  function getCatalog() {
    if (window.__gnCatalogCache) return window.__gnCatalogCache;
    const el = document.getElementById("gnCatalogData");
    const empty = {
      customers: [],
      tariffs: [],
      devices: [],
      default_hourly_rate: 60000,
      operator_label: "",
    };
    if (!el || !el.dataset.json) return empty;
    try {
      const parsed = JSON.parse(el.dataset.json);
      window.__gnCatalogCache = {
        customers: Array.isArray(parsed.customers) ? parsed.customers : [],
        tariffs: Array.isArray(parsed.tariffs) ? parsed.tariffs : [],
        devices: Array.isArray(parsed.devices) ? parsed.devices : [],
        default_hourly_rate: Number(parsed.default_hourly_rate) || 60000,
        operator_label: String(parsed.operator_label || ""),
      };
      return window.__gnCatalogCache;
    } catch (e) {
      return empty;
    }
  }

  function fmtToman(n) {
    const val = Math.round(Number(n) || 0);
    return val.toLocaleString("fa-IR") + " تومان";
  }

  function disconnectPolicyLabel(policy) {
    if (policy === "AUTO_STOP") return "پایان خودکار نشست هنگام قطع شبکه";
    if (policy === "CONTINUE") return "ادامه شمارنده در زمان قطع ارتباط";
    return "توقف موقت شمارنده تا اتصال مجدد";
  }

  // Session start: populate/sync customer personal rates + salon tariffs.
  function syncRateOptions(customerSelect, preferDeviceTariffId) {
    const form = customerSelect.form || customerSelect.closest("form");
    if (!form) return;
    const rateSelect = form.querySelector("[data-gn-rate-select]");
    if (!rateSelect) return;

    const cat = getCatalog();
    const customerId = customerSelect.value;
    const cust = cat.customers.find((c) => c.id === customerId) || null;

    if (rateSelect.dataset.gnDynamicRates === "1" && cat.customers.length) {
      const prevVal = rateSelect.value;
      rateSelect.innerHTML = "";
      const autoOpt = document.createElement("option");
      autoOpt.value = "";
      if (cust) {
        autoOpt.textContent = `پیش‌فرض خودکار (${cust.effective_rate_source}: ${fmtToman(cust.effective_rate)} / ساعت)`;
      } else {
        autoOpt.textContent = "پیش‌فرض خودکار مشتری / گروه / نرخ پایه";
      }
      rateSelect.appendChild(autoOpt);

      if (cust && Array.isArray(cust.rates) && cust.rates.length) {
        const ogPersonal = document.createElement("optgroup");
        ogPersonal.label = "تعرفه‌های اختصاصی مشتری";
        cust.rates.forEach((r) => {
          const opt = document.createElement("option");
          opt.value = "rate:" + r.id;
          opt.dataset.hourlyRate = String(r.hourly_rate);
          opt.dataset.rateLabel = r.name;
          opt.textContent = `${r.name} (${Number(r.hourly_rate).toLocaleString("fa-IR")} ت/ساعت)${r.is_default ? " ★ پیش‌فرض" : ""}`;
          ogPersonal.appendChild(opt);
        });
        rateSelect.appendChild(ogPersonal);
      }

      if (cat.tariffs.length) {
        const ogTariffs = document.createElement("optgroup");
        ogTariffs.label = "تعرفه‌های سالن";
        cat.tariffs.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = "tariff:" + t.id;
          opt.dataset.hourlyRate = String(t.hourly_rate);
          opt.dataset.rateLabel = t.name;
          opt.textContent = `${t.name} (${Number(t.hourly_rate).toLocaleString("fa-IR")} ت/ساعت)`;
          ogTariffs.appendChild(opt);
        });
        rateSelect.appendChild(ogTariffs);
      }

      const stillValid = Array.from(rateSelect.options).some((o) => o.value === prevVal && prevVal !== "");
      if (stillValid) {
        rateSelect.value = prevVal;
      } else if (cust && cust.rates && cust.rates.some((r) => r.is_default)) {
        const defR = cust.rates.find((r) => r.is_default);
        rateSelect.value = "rate:" + defR.id;
      } else if (preferDeviceTariffId) {
        const hasT = cat.tariffs.some((t) => t.id === preferDeviceTariffId);
        rateSelect.value = hasT ? "tariff:" + preferDeviceTariffId : "";
      } else {
        rateSelect.value = "";
      }
      return;
    }

    // Legacy static rate options filter
    let selectedStillValid = false;
    Array.from(rateSelect.options).forEach(function (option) {
      if (!option.value) return;
      const owner = option.getAttribute("data-customer");
      if (!owner) {
        if (option.selected) selectedStillValid = true;
        return;
      }
      const matches = owner === customerId;
      option.hidden = !matches;
      option.disabled = !matches;
      if (matches && option.selected) selectedStillValid = true;
    });
    if (!selectedStillValid) rateSelect.value = "";
  }

  function updateGuidedSessionPanel(form) {
    if (!form) return;
    const cat = getCatalog();
    const custField =
      form.querySelector("[data-gn-customer-select]") ||
      form.querySelector("[data-gn-locked-customer]");
    const devField =
      form.querySelector("[data-gn-device-select]") ||
      form.querySelector("[data-gn-locked-device]");
    const rateSelect = form.querySelector("[data-gn-rate-select]");
    const modeInput =
      form.querySelector('input[name="billing_mode"]:checked') ||
      form.querySelector('select[name="billing_mode"]');
    const minsInput = form.querySelector('input[name="planned_duration_minutes"]');
    const policyField =
      form.querySelector('input[name="disconnect_policy"]:checked') ||
      form.querySelector('select[name="disconnect_policy"]');

    const custId = custField ? custField.value : "";
    const devId = devField ? devField.value : "";
    const cust = cat.customers.find((c) => c.id === custId) || null;
    const dev = cat.devices.find((d) => d.id === devId) || null;

    if (form.dataset.actionTemplate && devId) {
      form.action = form.dataset.actionTemplate.replace("__ID__", devId);
    }

    let hourlyRate = cust ? Number(cust.effective_rate) : cat.default_hourly_rate;
    let rateName = cust ? cust.effective_rate_source : "نرخ پیش‌فرض";
    if (rateSelect && rateSelect.value) {
      const selOpt = rateSelect.options[rateSelect.selectedIndex];
      if (selOpt && selOpt.dataset.hourlyRate) {
        hourlyRate = Number(selOpt.dataset.hourlyRate) || hourlyRate;
        rateName = selOpt.dataset.rateLabel || selOpt.textContent;
      }
    } else if (dev && dev.default_tariff_id && !(cust && cust.rates && cust.rates.some((r) => r.is_default))) {
      const devTariff = cat.tariffs.find((t) => t.id === dev.default_tariff_id);
      if (devTariff && !cust) {
        hourlyRate = Number(devTariff.hourly_rate);
        rateName = devTariff.name;
      }
    }

    const billingMode = modeInput ? modeInput.value : "CREDIT";
    const timedWrap = form.querySelector("[data-gn-gs-timed-wrap]");
    if (timedWrap) {
      timedWrap.hidden = billingMode !== "TIMED";
    }
    if (minsInput) {
      minsInput.required = billingMode === "TIMED";
    }

    const plannedMins = Math.max(5, parseInt(normalizeDigits(minsInput ? minsInput.value : "60"), 10) || 60);
    const estCost = billingMode === "TIMED" ? Math.round((hourlyRate * plannedMins) / 60) : hourlyRate;
    const balance = cust ? Number(cust.balance) : 0;
    const available = cust ? Number(cust.available) : 0;
    const afterEst = balance - estCost;
    const maxHours = hourlyRate > 0 ? Math.floor((available / hourlyRate) * 60) : 0;
    const policyVal = policyField ? policyField.value : "PAUSE";

    const balEl = form.querySelector("[data-gn-gs-balance]");
    if (balEl) {
      balEl.textContent = cust
        ? `${fmtToman(balance)} (اعتبار کل: ${fmtToman(available)})`
        : "مشتری انتخاب نشده";
    }
    const rateEl = form.querySelector("[data-gn-gs-rate]");
    if (rateEl) {
      rateEl.textContent = `${fmtToman(hourlyRate)} / ساعت (${rateName})`;
    }
    const estEl = form.querySelector("[data-gn-gs-estimate]");
    if (estEl) {
      if (billingMode === "TIMED") {
        estEl.textContent = `${fmtToman(estCost)} برای ${plannedMins} دقیقه (مانده تقریبی: ${fmtToman(afterEst)})`;
      } else {
        const mh = Math.floor(maxHours / 60);
        const mm = maxHours % 60;
        const durTxt = maxHours > 0 ? `${mh > 0 ? mh + " ساعت و " : ""}${mm} دقیقه` : "۰ دقیقه (نیاز به شارژ)";
        estEl.textContent = `۱ ساعت ≈ ${fmtToman(hourlyRate)} · حداکثر زمان با اعتبار فعلی: ${durTxt}`;
      }
    }
    const warnEl = form.querySelector("[data-gn-gs-warn]");
    const submitBtn = form.querySelector('button[type="submit"]');
    if (warnEl) {
      const debt = cust ? Number(cust.debt_balance || 0) : 0;
      if (!cust) {
        warnEl.hidden = true;
        if (submitBtn) submitBtn.disabled = false;
      } else if (available <= 0) {
        warnEl.hidden = false;
        warnEl.textContent = "خطا: موجودی کیف پول مشتری صفر است! شروع بازی بدون اعتبار مجاز نیست؛ ابتدا حساب را شارژ کنید.";
        if (submitBtn) submitBtn.disabled = true;
      } else if (debt > 0 && available <= 0) {
        warnEl.hidden = false;
        warnEl.textContent = `خطا: مشتری دارای بدهی تسویه‌نشده (${fmtToman(debt)}) با موجودی صفر است. تا زمان تسویه بدهی، امکان شروع بازی وجود ندارد.`;
        if (submitBtn) submitBtn.disabled = true;
      } else if (billingMode === "TIMED" && estCost > available) {
        warnEl.hidden = false;
        warnEl.textContent = `هشدار: موجودی فعلی (${fmtToman(available)}) از برآورد هزینه (${fmtToman(estCost)}) کمتر است.`;
        if (submitBtn) submitBtn.disabled = false;
      } else {
        warnEl.hidden = true;
        if (submitBtn) submitBtn.disabled = false;
      }
    }

    const sumCust = form.querySelector("[data-gn-gs-sum-customer]");
    const sumDev = form.querySelector("[data-gn-gs-sum-device]");
    const sumMode = form.querySelector("[data-gn-gs-sum-mode]");
    const sumCost = form.querySelector("[data-gn-gs-sum-cost]");
    const sumPolicy = form.querySelector("[data-gn-gs-sum-policy]");
    if (sumCust) sumCust.textContent = cust ? cust.full_name : "—";
    if (sumDev) {
      let devText = dev ? dev.name : "—";
      if (!dev && devField && devField.tagName === "SELECT" && devField.selectedIndex >= 0) {
        devText = devField.options[devField.selectedIndex].textContent;
      }
      const staticDevName = form.querySelector("#startSessionDeviceName");
      if (!dev && staticDevName && staticDevName.textContent.trim()) {
        devText = staticDevName.textContent.trim();
      }
      sumDev.textContent = devText;
    }
    if (sumMode) {
      sumMode.textContent =
        billingMode === "TIMED"
          ? `زمانی (${plannedMins} دقیقه · ${fmtToman(hourlyRate)}/ساعت)`
          : `اعتبارمحور (${fmtToman(hourlyRate)}/ساعت)`;
    }
    if (sumCost) {
      sumCost.textContent =
        billingMode === "TIMED"
          ? fmtToman(estCost)
          : `برآورد ۱ ساعت: ${fmtToman(hourlyRate)}`;
    }
    if (sumPolicy) {
      sumPolicy.textContent = disconnectPolicyLabel(policyVal);
    }
  }

  function wireRateSelects() {
    document.querySelectorAll("[data-gn-customer-select]").forEach(function (select) {
      if (select.dataset.gnRateWired !== "1") {
        select.dataset.gnRateWired = "1";
        select.addEventListener("change", function () {
          const form = select.form || select.closest("form");
          const devSel = form ? form.querySelector("[data-gn-device-select]") : null;
          const dev = devSel ? getCatalog().devices.find((d) => d.id === devSel.value) : null;
          syncRateOptions(select, dev ? dev.default_tariff_id : "");
          if (form && form.hasAttribute("data-gn-guided-session")) {
            updateGuidedSessionPanel(form);
          }
        });
      }
      syncRateOptions(select, "");
    });

    document.querySelectorAll("form[data-gn-guided-session]").forEach(function (form) {
      if (form.dataset.gnGuidedWired !== "1") {
        form.dataset.gnGuidedWired = "1";
        form.addEventListener("change", function (ev) {
          if (ev.target && ev.target.hasAttribute("data-gn-device-select")) {
            const custSel = form.querySelector("[data-gn-customer-select]");
            const dev = getCatalog().devices.find((d) => d.id === ev.target.value);
            if (custSel) syncRateOptions(custSel, dev ? dev.default_tariff_id : "");
          }
          if (ev.target && ev.target.hasAttribute("data-gn-gs-confirm")) {
            const box = ev.target.closest(".gn-confirm-check");
            if (box && ev.target.checked) box.classList.remove("is-invalid");
            const err = form.querySelector("[data-gn-gs-confirm-err]");
            if (err && ev.target.checked) err.hidden = true;
          }
          updateGuidedSessionPanel(form);
        });
        form.addEventListener("input", function () {
          updateGuidedSessionPanel(form);
        });
      }
      updateGuidedSessionPanel(form);
    });
  }

  function wireAll() {
    wireRateSelects();
    wireEdgeSelects();
    stampTimerAnchors();
  }

  // Smart clickable station cards (works across HTMX live swaps via delegation)
  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (e.target.closest("a, button, form, input, select, textarea, label, summary, details, [data-no-card-nav]")) {
      return;
    }
    const card = e.target.closest("[data-card-href]");
    if (card && card.dataset.cardHref) {
      window.location.href = card.dataset.cardHref;
    }
  });

  // Fallback light-dismiss when dialog closedBy="any" is unsupported
  function wireDialogLightDismiss() {
    const nativeSupported = "closedBy" in HTMLDialogElement.prototype;
    const outside = (e, dialog) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    document.querySelectorAll('dialog[closedby="any"], dialog.gn-dialog').forEach(function (dialog) {
      if (dialog.dataset.gnDismissWired === "1") return;
      dialog.dataset.gnDismissWired = "1";
      dialog.addEventListener("close", function () {
        dialog.returnValue = "";
      });
      if (nativeSupported && dialog.getAttribute("closedby") === "any") return;
      let pressedOutside = false;
      dialog.addEventListener("pointerdown", function (e) { pressedOutside = outside(e, dialog); });
      dialog.addEventListener("pointerup", function (e) {
        if (pressedOutside && outside(e, dialog)) dialog.close();
      });
    });
  }

  // -------------------------------------------------------------------------
  // CSP-safe Helpers & Event Delegation (Zero inline onclick/onsubmit/script)
  // -------------------------------------------------------------------------
  function wireActionSelects() {
    document.querySelectorAll("select[data-gn-action-select]").forEach(function (sel) {
      const opt = sel.options[sel.selectedIndex];
      const form = document.querySelector(sel.dataset.gnActionSelect);
      if (form && opt && opt.dataset.actionUrl) {
        form.action = opt.dataset.actionUrl;
      }
    });
  }

  function formatDurationHMS(diff) {
    const h = Math.floor(diff / 3600).toString().padStart(2, "0");
    const m = Math.floor((diff % 3600) / 60).toString().padStart(2, "0");
    const s = (diff % 60).toString().padStart(2, "0");
    return `${h}:${m}:${s}`;
  }

  function stampTimerAnchors() {
    const nowSec = Math.floor(Date.now() / 1000);
    document
      .querySelectorAll(".baz-timer-badge[data-elapsed], .baz-timer-badge[data-started], [data-gn-countdown-seconds]")
      .forEach(function (el) {
        if (!el.dataset.gnLoadedAt) {
          el.dataset.gnLoadedAt = String(nowSec);
        }
      });
  }

  function startGlobalTimerTick() {
    stampTimerAnchors();
    if (window.__gnTimerTickStarted) return;
    window.__gnTimerTickStarted = true;
    setInterval(function () {
      const now = Math.floor(Date.now() / 1000);
      document.querySelectorAll(".baz-timer-badge").forEach(function (el) {
        const paused = el.getAttribute("data-paused") === "1";
        const baseElapsedAttr = el.getAttribute("data-elapsed");
        if (baseElapsedAttr !== null) {
          const baseElapsed = parseInt(baseElapsedAttr || "0", 10);
          const loadedAt = parseInt(el.dataset.gnLoadedAt || String(now), 10);
          const diff = paused ? baseElapsed : Math.max(0, baseElapsed + (now - loadedAt));
          el.innerHTML =
            '<i class="ti ti-clock"></i> ' +
            formatDurationHMS(diff) +
            (paused ? ' <span class="ms-1">(متوقف)</span>' : "");
          return;
        }
        const started = parseInt(el.getAttribute("data-started") || "0", 10);
        if (started > 0) {
          const diff = Math.max(0, now - started);
          el.innerHTML = '<i class="ti ti-clock"></i> ' + formatDurationHMS(diff);
        }
      });

      document.querySelectorAll("[data-gn-countdown-seconds]").forEach(function (el) {
        const paused = el.getAttribute("data-paused") === "1";
        const baseRem = parseInt(el.getAttribute("data-gn-countdown-seconds") || "0", 10);
        const loadedAt = parseInt(el.dataset.gnLoadedAt || String(now), 10);
        const rem = paused ? baseRem : Math.max(0, baseRem - (now - loadedAt));
        const h = Math.floor(rem / 3600);
        const m = Math.floor((rem % 3600) / 60);
        el.textContent = rem > 0 ? `${h}س ${m}د` : "۰د";
      });
    }, 1000);
  }

  function normalizeDigits(str) {
    return String(str || "")
      .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
      .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
      .replace(/[,٬\s]/g, "");
  }

  // Unified Rahro & Wallet Recharge Calculator (works in cloud & edge customer detail + rahro modal)
  function getRechargeRate(tier) {
    if (tier === "CADRE_SENIOR" || tier === "cadre_or_senior") return 20000;
    if (tier === "RAHRO_STUDENT" || tier === "rahro_student") return 40000;
    return 60000;
  }

  function applyRechargeHours(root, hours, clickedBtn) {
    const tier = root.dataset.tier || "REGULAR";
    const hasQuota = root.dataset.hasQuota === "1";
    const remainingQuotas = parseInt(root.dataset.remainingQuotas || "0", 10) || 0;
    const isModal = root.hasAttribute("data-gn-modal-recharge");
    const activeClass = isModal ? "primary" : "btn-active";

    const btnWrap = root.querySelector("[data-gn-hours-wrap]");
    if (btnWrap) {
      btnWrap.querySelectorAll("[data-gn-recharge-hour]").forEach((b) => b.classList.remove(activeClass));
      if (clickedBtn) {
        clickedBtn.classList.add(activeClass);
      } else {
        const t = btnWrap.querySelector(`[data-gn-recharge-hour="${hours}"]`);
        if (t) t.classList.add(activeClass);
      }
    }

    const hoursInput = root.querySelector("[data-gn-hours-input]");
    if (hoursInput) hoursInput.value = String(hours);

    let amount = 0;
    let couponApplied = false;
    let couponHours = 0;
    let normalHours = hours;
    if (tier === "CADRE_SENIOR" || tier === "cadre_or_senior" || tier.includes("CADRE")) {
      amount = hours * 20000;
    } else if (tier === "RAHRO_STUDENT" || tier === "rahro_student" || tier === "STUDENT_5_7" || tier.includes("STUDENT") || tier.includes("LEAGUE") || tier.includes("RAHRO")) {
      const chk = root.querySelector("[data-gn-recharge-coupon]");
      const wantCoupon = chk ? chk.checked : hasQuota;
      if (wantCoupon && hasQuota && remainingQuotas > 0) {
        couponApplied = true;
        couponHours = Math.min(hours, remainingQuotas);
        normalHours = hours - couponHours;
        amount = couponHours * 20000 + normalHours * 40000;
      } else {
        amount = hours * 40000;
      }
    } else {
      amount = hours * 60000;
    }

    const couponInput = root.querySelector("[data-gn-coupon-input]");
    if (couponInput) couponInput.value = couponApplied ? "50" : "";

    const amtInput = root.querySelector("[data-gn-recharge-amount]");
    if (amtInput) amtInput.value = String(amount);

    const exp = root.querySelector("[data-gn-explain-text]");
    if (exp) {
      const accentColor = isModal ? "#2dd4bf" : "#047857";
      const blueColor = isModal ? "#38bdf8" : "#2563eb";
      const amtText = Number(amount || 0).toLocaleString("fa-IR");
      if (tier === "CADRE_SENIOR" || tier === "cadre_or_senior") {
        exp.innerHTML =
          `تعرفه کادر و پایه ۸ و ۹: <strong>ساعتی ۲۰,۰۰۰ ت</strong> | مدت بازی: <strong>${hours} ساعت</strong><br>` +
          `مبلغ دریافتی نقد / کارتخوان: <strong style="color: ${accentColor}; font-size: 15px;">${amtText} تومان</strong>`;
      } else if (couponApplied) {
        const rateDetail =
          normalHours > 0
            ? `${couponHours} ساعت سهمیه ۵۰٪ (<strong style="color: ${blueColor};">۲۰,۰۰۰ ت</strong>) + ${normalHours} ساعت تعرفه عادی (<strong>۴۰,۰۰۰ ت</strong>)`
            : `نرخ کلاینت برای ${hours} ساعت روی <strong style="color: ${blueColor};">۲۰,۰۰۰ ت</strong> تنظیم شده`;
        exp.innerHTML =
          `🎁 <strong>${couponHours} سهمیه ماهانه ۵۰٪ رهرو</strong> اعمال می‌شود (۰ امتیاز کسر می‌گردد).<br>` +
          `${rateDetail} و مبلغ <strong style="color: ${accentColor}; font-size: 15px;">${amtText} تومان</strong> به کیف پول افزوده می‌شود.`;
      } else if (tier === "RAHRO_STUDENT" || tier === "rahro_student" || tier === "STUDENT_5_7" || tier.includes("STUDENT") || tier.includes("LEAGUE") || tier.includes("RAHRO")) {
        exp.innerHTML =
          `تعرفه اعضای رهرو: <strong>ساعتی ۴۰,۰۰۰ ت</strong> | مدت بازی: <strong>${hours} ساعت</strong><br>` +
          `مبلغ دریافتی نقد / کارتخوان: <strong style="color: ${accentColor}; font-size: 15px;">${amtText} تومان</strong>`;
      } else {
        exp.innerHTML =
          `تعرفه آزاد کاربر عادی: <strong>ساعتی ۶۰,۰۰۰ ت</strong> | مدت بازی: <strong>${hours} ساعت</strong><br>` +
          `مبلغ دریافتی نقد / کارتخوان: <strong style="color: ${accentColor}; font-size: 15px;">${amtText} تومان</strong>`;
      }
    }
  }

  function applyRechargeCustom(root, clickedBtn) {
    const isModal = root.hasAttribute("data-gn-modal-recharge");
    const activeClass = isModal ? "primary" : "btn-active";
    const btnWrap = root.querySelector("[data-gn-hours-wrap]");
    if (btnWrap) {
      btnWrap.querySelectorAll("[data-gn-recharge-hour]").forEach((b) => b.classList.remove(activeClass));
      if (clickedBtn) clickedBtn.classList.add(activeClass);
    }
    const hoursInput = root.querySelector("[data-gn-hours-input]");
    if (hoursInput) hoursInput.value = "custom";
    const amtInput = root.querySelector("[data-gn-recharge-amount]");
    if (amtInput) {
      amtInput.focus();
      if (typeof amtInput.select === "function") amtInput.select();
      updateRechargeCustomText(root, amtInput.value);
    }
  }

  function updateRechargeCustomText(root, val) {
    const exp = root.querySelector("[data-gn-explain-text]");
    if (!exp) return;
    const tier = root.dataset.tier || "REGULAR";
    const amt = parseInt(normalizeDigits(val), 10) || 0;
    const rate = getRechargeRate(tier);
    const hours = amt > 0 ? amt / rate : 0;
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    let timeStr = "۰ دقیقه";
    if (h > 0 && m > 0) timeStr = `${h} ساعت و ${m} دقیقه`;
    else if (h > 0) timeStr = `${h} ساعت کامل`;
    else if (m > 0) timeStr = `${m} دقیقه`;

    const tierTitle =
      tier === "CADRE_SENIOR" || tier === "cadre_or_senior"
        ? "کادر و پایه ۸ و ۹ (ساعتی ۲۰,۰۰۰ ت)"
        : tier === "RAHRO_STUDENT" || tier === "rahro_student"
          ? "اعضای رهرو پایه ۵ تا ۷ (ساعتی ۴۰,۰۰۰ ت)"
          : "کاربر عادی (ساعتی ۶۰,۰۰۰ ت)";
    const accentColor = root.hasAttribute("data-gn-modal-recharge") ? "#2dd4bf" : "#047857";
    exp.innerHTML =
      `مبلغ دریافتی: <strong>${amt.toLocaleString("fa-IR")} تومان</strong><br>` +
      `تعرفه فعال: <strong>${tierTitle}</strong><br>` +
      `زمان بازی معادل با این شارژ: <strong style="color: ${accentColor}; font-size: 13.5px;">${timeStr}</strong>`;
  }

  function updateWalletFormSummary(form) {
    if (!form) return;
    const sum = form.querySelector("[data-gn-wallet-summary]") || form;
    const current = Number(form.dataset.currentBalance || 0) || 0;
    const custName = form.dataset.customerName || "";
    const cat = getCatalog();
    const opName = form.dataset.operator || cat.operator_label || "اپراتور";

    const rawInput =
      form.querySelector("[data-adjust-raw]") ||
      form.querySelector("[data-gn-recharge-amount]") ||
      form.querySelector('input[name="amount"]');
    const modeSel = form.querySelector("[data-adjust-mode]");
    const noteInput =
      form.querySelector('input[name="note"]') ||
      form.querySelector('input[name="reason"]') ||
      form.querySelector('textarea[name="note"]');

    const parsedRaw = Math.max(0, parseInt(normalizeDigits(rawInput ? rawInput.value : "0"), 10) || 0);
    let signedDelta = parsedRaw;
    if (modeSel) {
      if (modeSel.value === "deduct") signedDelta = -Math.abs(parsedRaw);
      else if (modeSel.value === "add") signedDelta = Math.abs(parsedRaw);
    }

    const custEl = sum.querySelector("[data-gn-ws-customer]");
    const curEl = sum.querySelector("[data-gn-ws-current]");
    const chgEl = sum.querySelector("[data-gn-ws-amount]");
    const afterEl = sum.querySelector("[data-gn-ws-after]");
    const opEl = sum.querySelector("[data-gn-ws-operator]");
    const noteEl = sum.querySelector("[data-gn-ws-note]");

    if (custEl && custName) custEl.textContent = custName;
    if (curEl) curEl.textContent = fmtToman(current);
    if (chgEl) {
      const sign = signedDelta > 0 ? "+" : signedDelta < 0 ? "−" : "";
      chgEl.textContent = `${sign}${fmtToman(Math.abs(signedDelta))}`;
      chgEl.classList.toggle("accent", signedDelta > 0);
      chgEl.classList.toggle("warn", signedDelta < 0);
    }
    if (afterEl) afterEl.textContent = fmtToman(current + signedDelta);
    if (opEl) opEl.textContent = opName;
    if (noteEl) {
      const nt = noteInput ? noteInput.value.trim() : "";
      if (nt) {
        noteEl.textContent = nt;
      } else if (modeSel && modeSel.value === "deduct") {
        noteEl.textContent = "کسر از کیف پول";
      } else {
        const payMethod = form.querySelector('input[name="payment_method"]:checked');
        if (payMethod) {
          noteEl.textContent = payMethod.value === "cash" ? "شارژ کیف پول (نقدی)" : "شارژ کیف پول (کارتخوان باجه)";
        } else {
          noteEl.textContent = "شارژ کیف پول";
        }
      }
    }
  }

  function wireRechargeRoots() {
    document.querySelectorAll("[data-gn-recharge-root]").forEach(function (root) {
      applyRechargeHours(root, 1, null);
      updateWalletFormSummary(root.closest("form") || root);
    });
    document.querySelectorAll("form[data-gn-transparent-wallet], form[data-gn-adjust-form]").forEach(function (form) {
      updateWalletFormSummary(form);
    });
  }

  function openStationSettingsModal(el) {
    const dialog = document.getElementById("stationSettingsModal");
    const form = document.getElementById("stationSettingsForm");
    if (!dialog || !form) return;
    const devId = el.dataset.deviceId || "";
    form.action = "/devices/" + devId + "/update";
    const resetForm = document.getElementById("stationResetForm");
    const deleteForm = document.getElementById("stationDeleteForm");
    if (resetForm) resetForm.action = "/devices/" + devId + "/reset";
    if (deleteForm) deleteForm.action = "/devices/" + devId + "/deactivate";
    const lbl = document.getElementById("settingsStationLabel");
    const nameIn = document.getElementById("settingsNameInput");
    const tariffSel = document.getElementById("settingsTariffSelect");
    const macIn = document.getElementById("settingsMacInput");
    const idleIn = document.getElementById("settingsIdleInput");
    const activeIn = document.getElementById("settingsIsActiveInput");
    if (lbl) lbl.textContent = el.dataset.deviceName || "";
    if (nameIn) nameIn.value = el.dataset.deviceName || "";
    if (tariffSel) tariffSel.value = el.dataset.tariffId || "";
    if (macIn) macIn.value = el.dataset.macAddress || "";
    if (idleIn) idleIn.value = el.dataset.idleShutdown || "15";
    if (activeIn) activeIn.checked = el.dataset.isActive === "1";
    dialog.showModal();
  }

  function openQuickDepositModal(el) {
    const dialog = document.getElementById("quickDepositModal");
    const form = document.getElementById("quickDepositForm");
    if (!dialog || !form) return;
    const cid = el.dataset.customerId || "";
    const tpl = form.dataset.actionTemplate || "/customers/__ID__/deposit";
    form.action = tpl.replace("__ID__", cid);

    const cat = getCatalog();
    const cust = cat.customers.find((c) => c.id === cid) || null;
    const custName = el.dataset.customerName || (cust ? cust.full_name : "");
    const balance = el.dataset.balance !== undefined && el.dataset.balance !== ""
      ? Number(el.dataset.balance) || 0
      : (cust ? Number(cust.balance) || 0 : 0);
    const operatorLabel = el.dataset.operator || cat.operator_label || form.dataset.operator || "اپراتور";

    form.dataset.customerName = custName;
    form.dataset.currentBalance = String(balance);
    form.dataset.operator = operatorLabel;

    const nameEl = document.getElementById("depositCustomerName");
    const balEl = document.getElementById("depositCurrentBalance");
    const amtEl = document.getElementById("depositAmountInput");
    const noteEl = document.getElementById("depositNoteInput");
    const chkEl = form.querySelector("[data-gn-wallet-confirm]");
    const errEl = form.querySelector("[data-gn-wallet-confirm-err]");
    if (nameEl) nameEl.textContent = custName;
    if (balEl) balEl.textContent = fmtToman(balance);
    if (amtEl) amtEl.value = "";
    if (noteEl && !noteEl.value.trim()) noteEl.value = "شارژ سریع کیف پول در باجه";
    if (chkEl) {
      chkEl.checked = true;
      const box = chkEl.closest(".gn-confirm-check");
      if (box) box.classList.remove("is-invalid");
    }
    if (errEl) errEl.hidden = true;

    updateWalletFormSummary(form);
    dialog.showModal();
    if (amtEl) setTimeout(() => amtEl.focus(), 100);
  }

  function openStartSessionModal(el) {
    const dialog = document.getElementById("startSessionModal");
    if (!dialog) return;
    const form = dialog.querySelector("form");
    const idEl = document.getElementById("startSessionDeviceId");
    const nameEl = document.getElementById("startSessionDeviceName");
    const devId = el.dataset.deviceId || "";
    if (idEl) idEl.value = devId;
    if (nameEl) nameEl.textContent = el.dataset.deviceName || "";
    if (form) {
      if (form.dataset.actionTemplate && devId) {
        form.action = form.dataset.actionTemplate.replace("__ID__", devId);
      }
      const custSel = form.querySelector("[data-gn-customer-select]");
      const devTariff = el.dataset.tariffId || "";
      if (custSel) syncRateOptions(custSel, devTariff);
      const chkEl = form.querySelector("[data-gn-gs-confirm]");
      if (chkEl) {
        chkEl.checked = true;
        const box = chkEl.closest(".gn-confirm-check");
        if (box) box.classList.remove("is-invalid");
      }
      const errEl = form.querySelector("[data-gn-gs-confirm-err]");
      if (errEl) errEl.hidden = true;
      updateGuidedSessionPanel(form);
    }
    dialog.showModal();
  }

  function openGameModalFromButton(mode, btn) {
    const modal = document.getElementById("gameModal");
    if (!modal) return;
    const title = document.getElementById("modalTitle");
    const submitBtn = document.getElementById("formSubmitBtn");
    if (mode === "add") {
      if (title) title.innerHTML = '<i class="ti ti-plus text-primary"></i> افزودن بازی جدید';
      document.getElementById("formAction").value = "add";
      document.getElementById("formGameId").value = "";
      document.getElementById("formName").value = "";
      document.getElementById("formCategory").value = "شوتر رقابتی";
      document.getElementById("formIcon").value = "🎯";
      document.getElementById("formExecutable").value = "";
      document.getElementById("formArguments").value = "";
      document.getElementById("formWorkingDir").value = "";
      document.getElementById("formActive").checked = true;
      if (submitBtn) submitBtn.innerHTML = '<i class="ti ti-check"></i> افزودن بازی';
    } else if (btn) {
      if (title) title.innerHTML = '<i class="ti ti-edit text-primary"></i> ویرایش بازی';
      document.getElementById("formAction").value = "edit";
      document.getElementById("formGameId").value = btn.dataset.id || "";
      document.getElementById("formName").value = btn.dataset.name || "";
      document.getElementById("formCategory").value = btn.dataset.category || "";
      document.getElementById("formIcon").value = btn.dataset.icon || "🎮";
      document.getElementById("formExecutable").value = btn.dataset.executable || "";
      document.getElementById("formArguments").value = btn.dataset.arguments || "";
      document.getElementById("formWorkingDir").value = btn.dataset.workingDir || "";
      document.getElementById("formActive").checked = btn.dataset.active === "1";
      if (submitBtn) submitBtn.innerHTML = '<i class="ti ti-check"></i> ذخیره تغییرات';
    }
    if (typeof modal.showModal === "function") {
      if (!modal.open) modal.showModal();
    } else {
      modal.style.display = "flex";
    }
  }

  function openAnnouncementModalFromButton(mode, btn) {
    const modal = document.getElementById("ann-modal");
    if (!modal) return;
    const modalTitle = document.getElementById("ann-modal-title");
    const actionInput = document.getElementById("ann-action");
    const idInput = document.getElementById("ann-id");
    const titleInput = document.getElementById("ann-title-input");
    const contentInput = document.getElementById("ann-content-input");
    const typeSelect = document.getElementById("ann-type-select");
    const priorityInput = document.getElementById("ann-priority-input");
    const activeInput = document.getElementById("ann-active-input");
    const submitBtn = document.getElementById("ann-submit-btn");

    if (mode === "add") {
      if (modalTitle) modalTitle.textContent = "ثبت اطلاعیه جدید سالن";
      if (actionInput) actionInput.value = "add";
      if (idInput) idInput.value = "";
      if (titleInput) titleInput.value = "";
      if (contentInput) contentInput.value = "";
      if (typeSelect) typeSelect.value = "info";
      if (priorityInput) priorityInput.value = "1";
      if (activeInput) activeInput.checked = true;
      if (submitBtn) submitBtn.innerHTML = '<i class="ti ti-check"></i> ذخیره و انتشار پیام';
    } else if (btn) {
      if (modalTitle) modalTitle.textContent = "ویرایش اطلاعیه سالن";
      if (actionInput) actionInput.value = "edit";
      if (idInput) idInput.value = btn.getAttribute("data-ann-id") || "";
      if (titleInput) titleInput.value = btn.getAttribute("data-ann-title") || "";
      if (contentInput) contentInput.value = btn.getAttribute("data-ann-content") || "";
      if (typeSelect) typeSelect.value = btn.getAttribute("data-ann-type") || "info";
      if (priorityInput) priorityInput.value = btn.getAttribute("data-ann-priority") || "1";
      if (activeInput) activeInput.checked = btn.getAttribute("data-ann-active") === "1";
      if (submitBtn) submitBtn.innerHTML = '<i class="ti ti-check"></i> ذخیره تغییرات';
    }
    if (typeof modal.showModal === "function") {
      if (!modal.open) modal.showModal();
    } else {
      modal.style.display = "flex";
    }
    if (titleInput) setTimeout(() => titleInput.focus(), 40);
  }

  document.addEventListener("click", function (e) {
    // 0. Copy tracking code pill
    const copyPill = e.target.closest("[data-copy-text]");
    if (copyPill) {
      const text = copyPill.dataset.copyText || "";
      if (text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(() => {});
        }
        const origHtml = copyPill.dataset.origHtml || copyPill.innerHTML;
        copyPill.dataset.origHtml = origHtml;
        copyPill.innerHTML = '<i class="ti ti-check"></i> کپی شد';
        setTimeout(() => {
          copyPill.innerHTML = origHtml;
        }, 1200);
      }
      return;
    }

    // 1. Confirm trigger on submit buttons (before other handlers)
    const confirmBtn = e.target.closest("button[data-gn-confirm], input[type='submit'][data-gn-confirm]");
    if (confirmBtn) {
      const msg = confirmBtn.dataset.gnConfirm || "آیا مطمئن هستید؟";
      if (!window.confirm(msg)) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    }

    // Modal data-bs-toggle & data-bs-dismiss support
    const modalToggle = e.target.closest("[data-bs-toggle='modal'], [data-toggle='modal']");
    if (modalToggle) {
      const targetSel = modalToggle.getAttribute("data-bs-target") || modalToggle.getAttribute("data-target") || modalToggle.getAttribute("href");
      if (targetSel && targetSel.startsWith("#")) {
        const modalEl = document.querySelector(targetSel);
        if (modalEl) {
          e.preventDefault();
          if (typeof modalEl.showModal === "function") {
            if (!modalEl.open) modalEl.showModal();
          } else {
            modalEl.style.display = "block";
            modalEl.classList.add("show");
          }
          return;
        }
      }
    }

    const modalDismiss = e.target.closest("[data-bs-dismiss='modal'], [data-dismiss='modal']");
    if (modalDismiss) {
      const modalEl = modalDismiss.closest("dialog, .modal");
      if (modalEl) {
        e.preventDefault();
        if (typeof modalEl.close === "function") {
          modalEl.close();
        } else {
          modalEl.style.display = "none";
          modalEl.classList.remove("show");
        }
        return;
      }
    }

    // 2. Sidebar mobile menu toggle
    if (e.target.closest("[data-gn-toggle-sidebar]")) {
      const sidebar = document.querySelector(".gn-sidebar");
      if (sidebar) sidebar.classList.toggle("is-open");
      return;
    }

    // 3. Screenshot modal button
    const shotBtn = e.target.closest("[data-gn-screenshot]");
    if (shotBtn) {
      e.preventDefault();
      e.stopPropagation();
      window.gnOpenScreenshot(shotBtn.dataset.gnScreenshot, shotBtn.dataset.deviceName || "PC");
      return;
    }

    // 4. Remote RDP modal button
    const remoteBtn = e.target.closest("[data-gn-remote]");
    if (remoteBtn) {
      e.preventDefault();
      e.stopPropagation();
      window.gnOpenRemote(remoteBtn.dataset.gnRemote, remoteBtn.dataset.deviceName || "PC");
      return;
    }

    // 5. Inline screenshot capture button
    const inlineShotBtn = e.target.closest("[data-gn-inline-shot]");
    if (inlineShotBtn) {
      e.preventDefault();
      window.gnInlineCaptureScreenshot(
        inlineShotBtn.dataset.gnInlineShot,
        inlineShotBtn.dataset.img,
        inlineShotBtn.dataset.status,
        inlineShotBtn.dataset.dl
      );
      return;
    }

    // 6. Edge station settings / quick deposit / start session modals
    const settingsBtn = e.target.closest("[data-gn-station-settings]");
    if (settingsBtn) {
      e.preventDefault();
      e.stopPropagation();
      openStationSettingsModal(settingsBtn);
      return;
    }

    const depositBtn = e.target.closest("[data-gn-quick-deposit]");
    if (depositBtn) {
      e.preventDefault();
      e.stopPropagation();
      openQuickDepositModal(depositBtn);
      return;
    }

    const depositPreset = e.target.closest("[data-gn-deposit-amount]");
    if (depositPreset) {
      const form = depositPreset.closest("form") || document.getElementById("quickDepositForm");
      const amtInput = form ? (form.querySelector('input[name="amount"]') || document.getElementById("depositAmountInput")) : document.getElementById("depositAmountInput");
      if (amtInput) {
        amtInput.value = depositPreset.dataset.gnDepositAmount || "";
        if (form) updateWalletFormSummary(form);
      }
      return;
    }

    const durationBtn = e.target.closest("[data-gn-gs-duration]");
    if (durationBtn) {
      const form = durationBtn.closest("form[data-gn-guided-session]");
      if (form) {
        const minsInput = form.querySelector('input[name="planned_duration_minutes"]');
        const timedRadio = form.querySelector('input[name="billing_mode"][value="TIMED"]');
        if (timedRadio) timedRadio.checked = true;
        if (minsInput) minsInput.value = durationBtn.dataset.gnGsDuration || "60";
        updateGuidedSessionPanel(form);
      }
      return;
    }

    const startBtn = e.target.closest("[data-gn-start-session]");
    if (startBtn) {
      e.preventDefault();
      e.stopPropagation();
      openStartSessionModal(startBtn);
      return;
    }

    // 7. Generic <dialog> open / close buttons
    const openDlgBtn = e.target.closest("[data-gn-dialog-open]");
    if (openDlgBtn) {
      e.preventDefault();
      e.stopPropagation();
      const targetId = openDlgBtn.dataset.gnDialogOpen;
      const dialog = targetId ? document.getElementById(targetId) : null;
      if (dialog && typeof dialog.showModal === "function" && !dialog.open) {
        dialog.showModal();
      }
      return;
    }
    const closeBtn = e.target.closest("[data-gn-dialog-close]");
    if (closeBtn) {
      const targetId = closeBtn.dataset.gnDialogClose;
      const dialog = targetId ? document.getElementById(targetId) : closeBtn.closest("dialog");
      if (dialog && typeof dialog.close === "function") dialog.close();
      return;
    }

    // 8. Deduct preset buttons
    const deductPreset = e.target.closest("[data-gn-preset-deduct]");
    if (deductPreset) {
      const formSel = deductPreset.dataset.form;
      const form = formSel
        ? document.querySelector(formSel)
        : deductPreset.closest("#wallet")?.querySelector("form[data-gn-adjust-form]");
      if (form) {
        const mode = form.querySelector("[data-adjust-mode]");
        const raw = form.querySelector("[data-adjust-raw]");
        if (mode) mode.value = "deduct";
        if (raw) {
          raw.value = deductPreset.dataset.gnPresetDeduct || "";
          raw.focus();
        }
        updateWalletFormSummary(form);
      }
      return;
    }

    // 9. Recharge hour / custom buttons
    const hourBtn = e.target.closest("[data-gn-recharge-hour]");
    if (hourBtn) {
      const root = hourBtn.closest("[data-gn-recharge-root], [data-gn-modal-recharge]");
      if (root) {
        const val = hourBtn.dataset.gnRechargeHour;
        if (val === "custom") applyRechargeCustom(root, hourBtn);
        else applyRechargeHours(root, parseFloat(val) || 1, hourBtn);
        updateWalletFormSummary(root.closest("form") || root);
      }
      return;
    }

    // 10. Rahro overlay modal controls
    const modalClose = e.target.closest("[data-gn-modal-close]");
    if (modalClose) {
      const target = document.getElementById(modalClose.dataset.gnModalClose || "");
      if (target) target.style.display = "none";
      return;
    }
    if (e.target.classList && e.target.classList.contains("recharge-modal-overlay")) {
      e.target.style.display = "none";
      return;
    }

    // 11. Games catalog modal controls
    const gameAddBtn = e.target.closest("[data-gn-game-add]");
    if (gameAddBtn) {
      e.preventDefault();
      e.stopPropagation();
      openGameModalFromButton("add", null);
      return;
    }
    const gameEditBtn = e.target.closest("[data-gn-game-edit]");
    if (gameEditBtn) {
      e.preventDefault();
      e.stopPropagation();
      openGameModalFromButton("edit", gameEditBtn);
      return;
    }
    if (e.target.closest("[data-gn-game-close]")) {
      e.preventDefault();
      const modal = document.getElementById("gameModal");
      if (modal) {
        if (typeof modal.close === "function" && modal.open) modal.close();
        else modal.style.display = "none";
      }
      return;
    }
    const catPill = e.target.closest("[data-gn-game-cat]");
    if (catPill) {
      e.preventDefault();
      const catEl = document.getElementById("formCategory");
      if (catEl) catEl.value = catPill.dataset.gnGameCat || "";
      return;
    }
    const iconPill = e.target.closest("[data-gn-game-icon]");
    if (iconPill) {
      e.preventDefault();
      const iconEl = document.getElementById("formIcon");
      if (iconEl) iconEl.value = iconPill.dataset.gnGameIcon || "";
      return;
    }

    // 11b. Announcements modal controls (CSP-safe)
    const annAddBtn = e.target.closest("[data-gn-ann-add]");
    if (annAddBtn) {
      e.preventDefault();
      e.stopPropagation();
      openAnnouncementModalFromButton("add", null);
      return;
    }
    const annEditBtn = e.target.closest("[data-gn-ann-edit]");
    if (annEditBtn) {
      e.preventDefault();
      e.stopPropagation();
      openAnnouncementModalFromButton("edit", annEditBtn);
      return;
    }

    // 12. Jump to an in-page tab and optional input focus
    const jumpTab = e.target.closest("[data-gn-jump-tab]");
    if (jumpTab) {
      e.preventDefault();
      const hash = jumpTab.dataset.gnJumpTab || "";
      const tab = document.querySelector(`[role="tab"][data-tab-hash="${CSS.escape(hash)}"]`);
      if (tab) {
        activateTab(tab, { focus: false, updateHash: true });
        if (jumpTab.dataset.focusId) {
          const inp = document.getElementById(jumpTab.dataset.focusId);
          if (inp) setTimeout(() => inp.focus(), 40);
        }
      }
    }
  });

  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.dataset.gnConfirm) {
      if (!window.confirm(form.dataset.gnConfirm)) {
        e.preventDefault();
        return;
      }
    }

    if (form.hasAttribute("data-gn-guided-session")) {
      const confirmChk = form.querySelector("[data-gn-gs-confirm]");
      if (confirmChk && !confirmChk.checked) {
        e.preventDefault();
        const box = confirmChk.closest(".gn-confirm-check");
        if (box) box.classList.add("is-invalid");
        const err = form.querySelector("[data-gn-gs-confirm-err]");
        if (err) err.hidden = false;
        confirmChk.focus();
        return;
      }
    }

    if (form.hasAttribute("data-gn-transparent-wallet") || form.hasAttribute("data-gn-adjust-form")) {
      const wChk = form.querySelector("[data-gn-wallet-confirm]");
      if (wChk && !wChk.checked) {
        e.preventDefault();
        const box = wChk.closest(".gn-confirm-check");
        if (box) box.classList.add("is-invalid");
        const err = form.querySelector("[data-gn-wallet-confirm-err]");
        if (err) err.hidden = false;
        wChk.focus();
        return;
      }
    }

    if (form.hasAttribute("data-gn-recharge-root") || form.querySelector("[data-gn-recharge-amount]")) {
      const amtInput = form.querySelector("[data-gn-recharge-amount]");
      if (amtInput) {
        const parsed = parseInt(normalizeDigits(amtInput.value), 10);
        if (!Number.isFinite(parsed) || parsed <= 0) {
          alert("لطفاً مبلغ معتبر و بزرگ‌تر از صفر وارد کنید.");
          amtInput.focus();
          e.preventDefault();
          return;
        }
        amtInput.value = String(parsed);
      }
    }

    if (form.hasAttribute("data-gn-adjust-form")) {
      const raw = form.querySelector("[data-adjust-raw]");
      const hidden = form.querySelector('input[name="amount"]');
      const mode = form.querySelector("[data-adjust-mode]");
      if (raw && hidden) {
        const n = parseInt(normalizeDigits(raw.value), 10);
        if (!Number.isFinite(n) || n === 0) {
          alert("لطفاً مبلغ معتبر و غیرصفر وارد کنید.");
          e.preventDefault();
          return;
        }
        if (mode && mode.value === "deduct") hidden.value = String(-Math.abs(n));
        else if (mode && mode.value === "add") hidden.value = String(Math.abs(n));
        else hidden.value = String(n);
      }
    }
  });

  document.addEventListener("change", function (e) {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;

    if (target instanceof HTMLSelectElement && target.hasAttribute("data-gn-auto-submit")) {
      if (target.form) target.form.submit();
      return;
    }

    if (target instanceof HTMLSelectElement && target.dataset.gnActionSelect) {
      const opt = target.options[target.selectedIndex];
      const form = document.querySelector(target.dataset.gnActionSelect);
      if (form && opt && opt.dataset.actionUrl) {
        form.action = opt.dataset.actionUrl;
      }
      return;
    }

    if (target.hasAttribute("data-gn-wallet-confirm")) {
      const box = target.closest(".gn-confirm-check");
      if (box && target.checked) box.classList.remove("is-invalid");
      const form = target.closest("form");
      const err = form ? form.querySelector("[data-gn-wallet-confirm-err]") : null;
      if (err && target.checked) err.hidden = true;
    }

    const walletForm = target.closest("form[data-gn-transparent-wallet], form[data-gn-adjust-form], form[data-gn-recharge-root]");
    if (walletForm) {
      updateWalletFormSummary(walletForm);
    }

    if (target.hasAttribute("data-gn-recharge-coupon")) {
      const root = target.closest("[data-gn-recharge-root], [data-gn-modal-recharge]");
      if (root) {
        const hInput = root.querySelector("[data-gn-hours-input]");
        if (hInput && hInput.value === "custom") {
          const couponInput = root.querySelector("[data-gn-coupon-input]");
          const amtInput = root.querySelector("[data-gn-recharge-amount]");
          if (couponInput) {
            couponInput.value = target.checked && root.dataset.hasQuota === "1" ? "50" : "";
          }
          if (amtInput) updateRechargeCustomText(root, amtInput.value);
        } else {
          const hoursNum = parseFloat(hInput ? hInput.value : "1") || 1;
          applyRechargeHours(root, hoursNum, null);
        }
        updateWalletFormSummary(root.closest("form") || root);
      }
    }
  });

  document.addEventListener("input", function (e) {
    const target = e.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    if (target.hasAttribute("data-gn-recharge-amount")) {
      const root = target.closest("[data-gn-recharge-root], [data-gn-modal-recharge]");
      if (root) updateRechargeCustomText(root, target.value);
    }
    const walletForm = target.closest("form[data-gn-transparent-wallet], form[data-gn-adjust-form], form[data-gn-recharge-root]");
    if (walletForm) {
      updateWalletFormSummary(walletForm);
    }
  });

  // -------------------------------------------------------------------------
  // Live Screenshot & Browser RDP Modal Controller
  // -------------------------------------------------------------------------
  const remoteState = {
    deviceId: "",
    deviceName: "",
    mode: "screenshot",
    ws: null,
    keepaliveTimer: null,
    lastDataUrl: "",
    frameCount: 0,
    fpsWindowStart: 0,
    interactive: true,
    lastMoveAt: 0,
  };

  function getCsrfToken() {
    const dlg = document.getElementById("gnRemoteDialog");
    if (dlg && dlg.dataset.csrf) return dlg.dataset.csrf;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setRemoteBadge(text, tone) {
    const badge = document.getElementById("gnRemoteStatus");
    if (!badge) return;
    badge.textContent = text;
    badge.style.color = tone === "ok" ? "#4ade80" : tone === "err" ? "#f87171" : "#fbbf24";
  }

  function closeRemoteSocket() {
    if (remoteState.keepaliveTimer) {
      clearInterval(remoteState.keepaliveTimer);
      remoteState.keepaliveTimer = null;
    }
    if (remoteState.ws) {
      try {
        if (remoteState.ws.readyState === WebSocket.OPEN) {
          remoteState.ws.send(JSON.stringify({ action: "stream_stop" }));
        }
        remoteState.ws.close(1000, "viewer closed");
      } catch {}
      remoteState.ws = null;
    }
  }

  function switchRemoteMode(mode) {
    remoteState.mode = mode;
    const tabShot = document.getElementById("gnTabShot");
    const tabRdp = document.getElementById("gnTabRdp");
    const shotBar = document.getElementById("gnShotToolbar");
    const rdpBar = document.getElementById("gnRdpToolbar");
    const img = document.getElementById("gnScreenshotImg");
    const canvas = document.getElementById("gnRemoteCanvas");
    const empty = document.getElementById("gnRemoteEmpty");

    if (tabShot) tabShot.classList.toggle("is-active", mode === "screenshot");
    if (tabRdp) tabRdp.classList.toggle("is-active", mode === "rdp");
    if (shotBar) shotBar.hidden = mode !== "screenshot";
    if (rdpBar) rdpBar.hidden = mode !== "rdp";

    if (mode === "screenshot") {
      closeRemoteSocket();
      if (canvas) canvas.hidden = true;
      if (img) img.hidden = !remoteState.lastDataUrl;
      if (empty) empty.hidden = !!remoteState.lastDataUrl;
      captureModalScreenshot();
    } else {
      if (img) img.hidden = true;
      if (canvas) canvas.hidden = false;
      if (empty) empty.hidden = true;
      openRemoteSocket();
    }
  }

  async function captureModalScreenshot() {
    if (!remoteState.deviceId) return;
    const img = document.getElementById("gnScreenshotImg");
    const empty = document.getElementById("gnRemoteEmpty");
    const meta = document.getElementById("gnShotMeta");
    const dl = document.getElementById("gnShotDownload");
    setRemoteBadge("در حال دریافت تصویر از کلاینت...", "warn");
    if (empty && !remoteState.lastDataUrl) {
      empty.hidden = false;
      empty.textContent = "در حال ارسال درخواست تصویر به کلاینت...";
    }

    try {
      const resp = await fetch(`/devices/${remoteState.deviceId}/screenshot/capture`, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      const data = await resp.json();
      if (!data.ok || !data.data_url) {
        setRemoteBadge(data.error || "خطا در دریافت تصویر", "err");
        if (empty && !remoteState.lastDataUrl) {
          empty.hidden = false;
          empty.textContent = data.error || "خطا در دریافت اسکرین‌شات";
        }
        return;
      }
      remoteState.lastDataUrl = data.data_url;
      if (img) {
        img.src = data.data_url;
        img.hidden = false;
        const placeholder = document.getElementById("edgeInlineShotPlaceholder");
        if (placeholder) placeholder.style.display = "none";
      }
      if (empty) empty.hidden = true;
      if (dl) {
        dl.href = data.data_url;
        dl.download = `${remoteState.deviceName || "client"}-${Date.now()}.jpg`;
        dl.hidden = false;
      }
      if (meta) {
        meta.textContent = `${data.width || "?"}×${data.height || "?"}${data.stale ? " (آخرین تصویر ثبت‌شده)" : ""}`;
      }
      setRemoteBadge(data.stale ? "تصویر کش‌شده" : "تصویر زنده دریافت شد", "ok");
    } catch (err) {
      setRemoteBadge("خطای ارتباط با سرور", "err");
      if (empty && !remoteState.lastDataUrl) {
        empty.hidden = false;
        empty.textContent = "خطای شبکه هنگام دریافت تصویر.";
      }
    }
  }

  function openRemoteSocket() {
    closeRemoteSocket();
    if (!remoteState.deviceId) return;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/remote/${remoteState.deviceId}/`;
    const canvas = document.getElementById("gnRemoteCanvas");
    const ctx = canvas ? canvas.getContext("2d") : null;
    const qualitySelect = document.getElementById("gnRdpQuality");

    setRemoteBadge("در حال برقراری تونل RDP...", "warn");
    remoteState.frameCount = 0;
    remoteState.fpsWindowStart = performance.now();

    const ws = new WebSocket(wsUrl);
    remoteState.ws = ws;

    ws.onopen = function () {
      setRemoteBadge("منتظر تصویر دسکتاپ...", "warn");
      sendRdpQuality();
      if (remoteState.keepaliveTimer) clearInterval(remoteState.keepaliveTimer);
      remoteState.keepaliveTimer = setInterval(function () {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "ping" }));
        }
      }, 5000);
    };

    ws.onmessage = function (ev) {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "viewer_ready") {
        if (!msg.online) {
          if (msg.power_status === "OFF" && !msg.lan_reachable) {
            setRemoteBadge("رایانه خاموش است (ارتباط شبکه قطع)", "err");
          } else if (msg.lan_reachable && !msg.online) {
            setRemoteBadge("سخت‌افزار روشن است ولی کلاینت اجرا نشده", "warn");
          } else {
            setRemoteBadge("کلاینت آفلاین است", "err");
          }
        }
        return;
      }
      if (msg.type === "frame" && msg.frame && msg.frame.data && ctx && canvas) {
        const src = `data:image/jpeg;base64,${msg.frame.data}`;
        remoteState.lastDataUrl = src;
        const frameImg = new Image();
        frameImg.onload = function () {
          if (canvas.width !== frameImg.width || canvas.height !== frameImg.height) {
            canvas.width = frameImg.width;
            canvas.height = frameImg.height;
          }
          ctx.drawImage(frameImg, 0, 0);
          remoteState.frameCount += 1;
          const now = performance.now();
          const dt = (now - remoteState.fpsWindowStart) / 1000;
          if (dt >= 1.5) {
            const fps = (remoteState.frameCount / dt).toFixed(1);
            setRemoteBadge(`متصل زنده · ${fps} FPS`, "ok");
            remoteState.frameCount = 0;
            remoteState.fpsWindowStart = now;
          } else {
            setRemoteBadge("متصل زنده (RDP فعال)", "ok");
          }
        };
        frameImg.src = src;
      }
    };

    ws.onclose = function (ev) {
      if (remoteState.ws === ws) {
        let reason = "اتصال RDP قطع شد";
        if (ev.code === 4401) reason = "عدم دسترسی (احراز هویت نامعتبر)";
        else if (ev.code === 4404) reason = "دستگاه یافت نشد";
        else if (ev.code === 1006) reason = "عدم پاسخ از کلاینت یا قطعی سوکت (کد 1006)";
        setRemoteBadge(reason, "err");
      }
    };

    ws.onerror = function () {
      setRemoteBadge("خطا در اتصال WebSocket", "err");
    };

    function sendRdpQuality() {
      if (ws.readyState !== WebSocket.OPEN) return;
      const mode = qualitySelect ? qualitySelect.value : "balanced";
      const cfg =
        mode === "high"
          ? { width: 1280, quality: 75, fps: 4 }
          : mode === "fast"
            ? { width: 720, quality: 50, fps: 6 }
            : { width: 1024, quality: 64, fps: 5 };
      ws.send(JSON.stringify({ action: "stream_start", ...cfg }));
    }

    if (qualitySelect) {
      qualitySelect.onchange = sendRdpQuality;
    }
  }

  function sendRemoteInput(eventObj) {
    if (!remoteState.interactive) return;
    if (!remoteState.ws || remoteState.ws.readyState !== WebSocket.OPEN) return;
    remoteState.ws.send(JSON.stringify({ action: "input", event: eventObj }));
  }

  function wireRemoteCanvasControls() {
    const canvas = document.getElementById("gnRemoteCanvas");
    const chk = document.getElementById("gnRdpInteractive");
    if (!canvas) return;

    function normPos(e) {
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return { x: 0.5, y: 0.5 };
      const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
      return { x, y };
    }

    canvas.addEventListener("mousemove", function (e) {
      const now = performance.now();
      if (now - remoteState.lastMoveAt < 40) return;
      remoteState.lastMoveAt = now;
      const p = normPos(e);
      sendRemoteInput({ kind: "mv", x: p.x, y: p.y });
    });

    canvas.addEventListener("mousedown", function (e) {
      e.preventDefault();
      canvas.focus();
      const p = normPos(e);
      sendRemoteInput({ kind: "md", button: e.button, x: p.x, y: p.y });
    });

    canvas.addEventListener("mouseup", function (e) {
      e.preventDefault();
      const p = normPos(e);
      sendRemoteInput({ kind: "mu", button: e.button, x: p.x, y: p.y });
    });

    canvas.addEventListener("contextmenu", function (e) {
      e.preventDefault();
    });

    canvas.addEventListener("wheel", function (e) {
      e.preventDefault();
      const p = normPos(e);
      const delta = e.deltaY < 0 ? 120 : -120;
      sendRemoteInput({ kind: "wh", delta, x: p.x, y: p.y });
    }, { passive: false });

    canvas.addEventListener("keydown", function (e) {
      if (!remoteState.interactive || remoteState.mode !== "rdp") return;
      if (e.code === "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      sendRemoteInput({ kind: "kd", code: e.code, keyCode: e.keyCode });
    });

    canvas.addEventListener("keyup", function (e) {
      if (!remoteState.interactive || remoteState.mode !== "rdp") return;
      if (e.code === "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      sendRemoteInput({ kind: "ku", code: e.code, keyCode: e.keyCode });
    });

    if (chk) {
      chk.addEventListener("change", function () {
        remoteState.interactive = chk.checked;
        canvas.classList.toggle("is-interactive", chk.checked);
      });
    }
  }

  function wireRemoteDialog() {
    const dlg = document.getElementById("gnRemoteDialog");
    if (!dlg) return;
    dlg.addEventListener("close", function () {
      closeRemoteSocket();
      dlg.returnValue = "";
    });
    const tabShot = document.getElementById("gnTabShot");
    const tabRdp = document.getElementById("gnTabRdp");
    const refreshBtn = document.getElementById("gnShotRefresh");
    if (tabShot) tabShot.addEventListener("click", () => switchRemoteMode("screenshot"));
    if (tabRdp) tabRdp.addEventListener("click", () => switchRemoteMode("rdp"));
    if (refreshBtn) refreshBtn.addEventListener("click", () => captureModalScreenshot());

    dlg.querySelectorAll("[data-rdp-combo]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const vks = btn.dataset.rdpCombo.split(",").map(Number).filter(Boolean);
        if (vks.length) sendRemoteInput({ kind: "combo", vks });
        const canvas = document.getElementById("gnRemoteCanvas");
        if (canvas) canvas.focus();
      });
    });

    wireRemoteCanvasControls();
  }

  window.gnOpenScreenshot = function (deviceId, deviceName) {
    const dlg = document.getElementById("gnRemoteDialog");
    if (!dlg) return;
    remoteState.deviceId = deviceId;
    remoteState.deviceName = deviceName || "PC";
    remoteState.lastDataUrl = "";
    const title = document.getElementById("gnRemoteTitle");
    if (title) title.textContent = `صفحه نمایش و کنترل ${remoteState.deviceName}`;
    if (!dlg.open) dlg.showModal();
    switchRemoteMode("screenshot");
  };

  window.gnOpenRemote = function (deviceId, deviceName) {
    const dlg = document.getElementById("gnRemoteDialog");
    if (!dlg) return;
    remoteState.deviceId = deviceId;
    remoteState.deviceName = deviceName || "PC";
    const title = document.getElementById("gnRemoteTitle");
    if (title) title.textContent = `کنترل زنده ${remoteState.deviceName} (RDP)`;
    if (!dlg.open) dlg.showModal();
    switchRemoteMode("rdp");
    setTimeout(() => {
      const c = document.getElementById("gnRemoteCanvas");
      if (c) c.focus();
    }, 100);
  };

  window.gnInlineCaptureScreenshot = async function (deviceId, imgId, statusId, dlId) {
    const img = document.getElementById(imgId);
    const status = document.getElementById(statusId);
    const dl = document.getElementById(dlId);
    if (status) status.textContent = "در حال دریافت اسکرین‌شات از کلاینت...";
    try {
      const resp = await fetch(`/devices/${deviceId}/screenshot/capture`, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken(), "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await resp.json();
      if (!data.ok || !data.data_url) {
        if (status) status.textContent = data.error || "خطا در دریافت تصویر";
        return;
      }
      if (img) {
        img.src = data.data_url;
        img.hidden = false;
        const placeholder = document.getElementById("edgeInlineShotPlaceholder");
        if (placeholder) placeholder.style.display = "none";
      }
      if (dl) {
        dl.href = data.data_url;
        dl.hidden = false;
      }
      if (status) {
        status.textContent = `تصویر دریافت شد (${data.width || "?"}×${data.height || "?"})`;
      }
    } catch {
      if (status) status.textContent = "خطا در ارتباط با سرور";
    }
  };

  // -------------------------------------------------------------------------
  // Accessible In-Page Tabs (ARIA tablist/tabpanel + RTL keyboard + #hash + until-found)
  // -------------------------------------------------------------------------
  function activateTab(tab, opts) {
    if (!tab) return;
    const options = opts || {};
    const container = tab.closest("[data-gn-tabs], .gn-tabs") || document;
    const tablist = tab.closest('[role="tablist"]') || container.querySelector('[role="tablist"]');
    if (!tablist) return;

    const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
    tabs.forEach(function (t) {
      const selected = t === tab;
      t.setAttribute("aria-selected", selected ? "true" : "false");
      t.setAttribute("tabindex", selected ? "0" : "-1");
      const panelId = t.dataset.tabPanel || t.getAttribute("aria-controls");
      const panel = panelId ? document.getElementById(panelId) : null;
      if (panel) {
        const hasFocusable = !!panel.querySelector('a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (selected) {
          panel.removeAttribute("hidden");
          if (!hasFocusable) panel.setAttribute("tabindex", "0");
        } else {
          panel.hidden = "until-found";
          if (!hasFocusable) panel.removeAttribute("tabindex");
        }
      }
    });

    if (typeof tab.scrollIntoView === "function" && (options.updateHash || options.scrollIntoView)) {
      tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    if (options.focus) tab.focus();
    const hash = tab.dataset.tabHash;
    if (options.updateHash && hash && window.history && window.history.replaceState) {
      try {
        window.history.replaceState(null, "", "#" + hash);
      } catch (e) {}
    }
  }

  function syncTabsFromHash() {
    const rawHash = (window.location.hash || "").replace(/^#/, "").trim();
    if (!rawHash) return;
    const targetByAttr = document.querySelector(`[role="tab"][data-tab-hash="${CSS.escape(rawHash)}"]`);
    if (targetByAttr) {
      activateTab(targetByAttr, { focus: false, updateHash: false });
      return;
    }
    const targetEl = document.getElementById(rawHash);
    if (targetEl) {
      const panel = targetEl.closest('[role="tabpanel"]');
      if (panel && panel.id) {
        const ownerTab =
          document.querySelector(`[role="tab"][data-tab-panel="${CSS.escape(panel.id)}"]`) ||
          document.querySelector(`[role="tab"][aria-controls="${CSS.escape(panel.id)}"]`);
        if (ownerTab) {
          activateTab(ownerTab, { focus: false, updateHash: false });
        }
      }
    }
  }

  function wireTabs() {
    document.querySelectorAll('[role="tablist"][data-gn-tablist]').forEach(function (tablist) {
      if (tablist.dataset.gnTabsWired === "1") return;
      tablist.dataset.gnTabsWired = "1";

      tablist.addEventListener("click", function (e) {
        const tab = e.target.closest('[role="tab"]');
        if (!tab || !tablist.contains(tab)) return;
        activateTab(tab, { focus: false, updateHash: true });
      });

      tablist.addEventListener("keydown", function (e) {
        const currentTab = e.target.closest('[role="tab"]');
        if (!currentTab || !tablist.contains(currentTab)) return;
        const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
        if (tabs.length < 2) return;
        const idx = tabs.indexOf(currentTab);
        const isRtl = window.getComputedStyle(tablist).direction === "rtl";

        let nextIdx = -1;
        if (e.key === "ArrowRight") {
          nextIdx = isRtl ? (idx - 1 + tabs.length) % tabs.length : (idx + 1) % tabs.length;
        } else if (e.key === "ArrowLeft") {
          nextIdx = isRtl ? (idx + 1) % tabs.length : (idx - 1 + tabs.length) % tabs.length;
        } else if (e.key === "Home") {
          nextIdx = 0;
        } else if (e.key === "End") {
          nextIdx = tabs.length - 1;
        }

        if (nextIdx >= 0) {
          e.preventDefault();
          activateTab(tabs[nextIdx], { focus: true, updateHash: true });
        }
      });
    });

    document.querySelectorAll('[role="tabpanel"]').forEach(function (panel) {
      if (panel.dataset.gnBeforematchWired === "1") return;
      panel.dataset.gnBeforematchWired = "1";
      panel.addEventListener("beforematch", function () {
        if (!panel.id) return;
        const ownerTab =
          document.querySelector(`[role="tab"][data-tab-panel="${CSS.escape(panel.id)}"]`) ||
          document.querySelector(`[role="tab"][aria-controls="${CSS.escape(panel.id)}"]`);
        if (ownerTab) activateTab(ownerTab, { focus: false, updateHash: false });
      });
    });

    syncTabsFromHash();
  }

  window.addEventListener("hashchange", syncTabsFromHash);

  function initExtras() {
    wireAll();
    wireTabs();
    wireActionSelects();
    wireRechargeRoots();
    wireDialogLightDismiss();
    wireRemoteDialog();
    startGlobalTimerTick();
  }

  document.addEventListener("htmx:afterSwap", function () {
    window.__gnCatalogCache = null;
    wireAll();
    wireTabs();
    wireDialogLightDismiss();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initExtras);
  } else {
    initExtras();
  }
})();
