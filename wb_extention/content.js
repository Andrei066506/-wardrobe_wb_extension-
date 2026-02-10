// Wardrobe content script:
// - injects "Подобрать образ" button on WB product pages (clothing only)
// - opens slide-out panel with 3 generated capsules from backend

const WARDROBE_BACKEND_BASE = "http://localhost:5000";

const WARDROBE = {
  rootId: "wardrobe-ext-root",
  buttonId: "wardrobe-ext-btn",
  panelId: "wardrobe-ext-panel",
  backdropId: "wardrobe-ext-backdrop",
};

function mountDebugBadge() {
  // Visual proof that content script is running on this page.
  if (document.getElementById("wardrobe-ext-debug-badge")) return;
  const badge = document.createElement("div");
  badge.id = "wardrobe-ext-debug-badge";
  badge.textContent = "Wardrobe: content script loaded";
  badge.style.position = "fixed";
  badge.style.left = "12px";
  badge.style.bottom = "12px";
  badge.style.zIndex = "2147483647";
  badge.style.padding = "8px 10px";
  badge.style.borderRadius = "999px";
  badge.style.background = "#1f1f1f";
  badge.style.color = "#fff";
  badge.style.fontSize = "12px";
  badge.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
  badge.style.boxShadow = "0 8px 18px rgba(0,0,0,0.25)";
  badge.style.opacity = "0.9";
  badge.style.cursor = "pointer";
  badge.title = "Click to hide";
  badge.addEventListener("click", () => badge.remove());
  document.documentElement.appendChild(badge);
}

function getCurrentProduct() {
  let nameEl =
    document.querySelector('h1') ||
    document.querySelector('[data-testid="product-name"]') ||
    document.querySelector('.product-page__header-title') ||
    document.querySelector('title');

  const nmIdMatch = window.location.pathname.match(/\/(\d+)\//);
  const nmId = nmIdMatch ? nmIdMatch[1] : null;
  const name = nameEl ? (nameEl.innerText || nameEl.textContent || "").trim() : null;

  if (nmId && name) return { nm_id: nmId, name };
  return null;
}

function isWbProductPage() {
  return (
    location.hostname.includes("wildberries.ru") &&
    /^\/catalog\/\d+\/detail\.aspx/.test(location.pathname)
  );
}

function guessIsClothingCategory() {
  // Heuristic (WB DOM changes often):
  // - look for breadcrumb texts containing "Одежда"
  // - or top-level section "Женщинам/Мужчинам/Детям" + clothing-ish keywords
  const textNorm = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();
  const hasAny = (hay, needles) => needles.some((n) => hay.includes(n));

  const needlesClothing = ["одежда"];
  const needlesSections = ["женщинам", "мужчинам", "детям"];
  const needlesClothingish = [
    "футболк",
    "рубашк",
    "толстовк",
    "худи",
    "джинс",
    "брюк",
    "куртк",
    "пальт",
    "ветровк",
    "плать",
    "юбк",
    "костюм",
    "свитер",
    "кардиган",
    "кроссовк",
    "ботинк",
    "туфл",
  ];

  // Breadcrumbs (try multiple selectors)
  const crumbEls = Array.from(
    document.querySelectorAll(
      'nav a, nav span, [data-testid*="breadcrumb"] a, [data-testid*="breadcrumb"] span, .breadcrumbs a, .breadcrumbs span'
    )
  );
  const crumbsText = textNorm(crumbEls.map((e) => e.textContent).join(" "));
  if (hasAny(crumbsText, needlesClothing)) return true;

  const titleText = textNorm(document.title);
  if (hasAny(crumbsText, needlesSections) && hasAny(titleText, needlesClothingish)) return true;

  // JSON-LD BreadcrumbList
  const ldJsonScripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
  for (const s of ldJsonScripts) {
    const raw = s.textContent || "";
    if (!raw) continue;
    try {
      const data = JSON.parse(raw);
      const items = Array.isArray(data) ? data : [data];
      for (const obj of items) {
        if (!obj || obj["@type"] !== "BreadcrumbList" || !Array.isArray(obj.itemListElement)) continue;
        const names = obj.itemListElement
          .map((it) => it?.item?.name || it?.name)
          .filter(Boolean)
          .map(textNorm)
          .join(" ");
        if (hasAny(names, needlesClothing)) return true;
      }
    } catch (_) {
      // ignore invalid JSON-LD
    }
  }

  return false;
}

function ensureRoot() {
  let root = document.getElementById(WARDROBE.rootId);
  if (root) return root;

  root = document.createElement("div");
  root.id = WARDROBE.rootId;
  root.style.all = "initial";
  root.style.position = "fixed";
  root.style.zIndex = "2147483647";
  root.style.top = "0";
  root.style.left = "0";
  root.style.width = "0";
  root.style.height = "0";
  document.documentElement.appendChild(root);
  return root;
}

function ensurePanel() {
  const root = ensureRoot();

  let backdrop = document.getElementById(WARDROBE.backdropId);
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = WARDROBE.backdropId;
    backdrop.style.position = "fixed";
    backdrop.style.inset = "0";
    backdrop.style.background = "rgba(0,0,0,0.35)";
    backdrop.style.display = "none";
    backdrop.style.zIndex = "2147483646";
    backdrop.addEventListener("click", () => closePanel());
    document.documentElement.appendChild(backdrop);
  }

  let panel = document.getElementById(WARDROBE.panelId);
  if (!panel) {
    panel = document.createElement("div");
    panel.id = WARDROBE.panelId;
    panel.style.position = "fixed";
    panel.style.top = "0";
    panel.style.right = "0";
    panel.style.height = "100vh";
    panel.style.width = "420px";
    panel.style.maxWidth = "92vw";
    panel.style.background = "#fff";
    panel.style.boxShadow = "0 10px 30px rgba(0,0,0,0.2)";
    panel.style.transform = "translateX(110%)";
    panel.style.transition = "transform 180ms ease";
    panel.style.zIndex = "2147483647";
    panel.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
    panel.style.color = "#1f1f1f";

    panel.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 14px;border-bottom:1px solid #e8e8e8;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div style="font-weight:800;font-size:16px;color:#cb11ab;">Wardrobe</div>
          <div id="wardrobe-subtitle" style="font-size:12px;color:#666;">Подбор образов</div>
        </div>
        <button id="wardrobe-close" style="all:unset;cursor:pointer;padding:8px 10px;border-radius:8px;background:#f4f5f7;font-weight:700;">✕</button>
      </div>
      <div id="wardrobe-body" style="padding:14px;overflow:auto;height:calc(100vh - 52px);">
        <div style="color:#666;font-size:13px;">Нажмите «Подобрать образ», чтобы сгенерировать капсулы.</div>
      </div>
      <style>
        @media (max-width: 720px) {
          #${WARDROBE.panelId} {
            top: auto !important;
            bottom: 0 !important;
            right: 0 !important;
            left: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
            height: 70vh !important;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
          }
          #${WARDROBE.panelId} #wardrobe-body {
            height: calc(70vh - 52px) !important;
          }
        }
      </style>
    `;

    root.appendChild(panel);

    panel.querySelector("#wardrobe-close").addEventListener("click", () => closePanel());
  }

  return { panel, backdrop };
}

function openPanel() {
  const { panel, backdrop } = ensurePanel();
  backdrop.style.display = "block";
  panel.style.transform = "translateX(0)";
}

function closePanel() {
  const panel = document.getElementById(WARDROBE.panelId);
  const backdrop = document.getElementById(WARDROBE.backdropId);
  if (backdrop) backdrop.style.display = "none";
  if (panel) panel.style.transform = "translateX(110%)";
}

function setPanelContent(html) {
  const body = document.getElementById("wardrobe-body");
  if (body) body.innerHTML = html;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatRub(v) {
  const num = Number(v);
  if (!Number.isFinite(num)) return "—";
  return `${num.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
}

function renderCapsules(capsules) {
  const blocks = capsules
    .map((cap, idx) => {
      const outfit = Array.isArray(cap?.outfit) ? cap.outfit : [];
      const style = cap?.anchor_style || "other";
      const styleLabels = {
        casual: "на каждый день",
        sport: "для тренировок",
        office: "для офиса",
        streetwear: "в стиле стритвир",
        elegant: "в элегантном стиле",
        other: "",
      };
      const styleLabel = styleLabels[style] || "";
      const title = `Образ ${idx + 1}${styleLabel ? ` ${styleLabel}` : ""}`;
      const total = outfit.reduce((acc, it) => acc + (Number(it?.price_rub) || 0), 0);

      const cardsHtml = outfit
        .map((it, i) => {
          const role = i === 0 ? "Основной товар" : `Рекомендация ${i}`;
          const img = (it?.image_url || "").trim();
          const link = (it?.link || "").trim();
          return `
            <div style="display:grid;grid-template-columns:72px 1fr;gap:10px;padding:10px;border:1px solid #eee;border-radius:12px;background:#fff;">
              <div style="width:72px;height:72px;border-radius:10px;background:#f4f5f7;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                ${
                  img
                    ? `<img src="${escapeHtml(img)}" alt="" style="width:72px;height:72px;object-fit:cover;">`
                    : `<div style="color:#999;font-size:12px;">no image</div>`
                }
              </div>
              <div style="min-width:0;">
                <div style="font-size:11px;color:#777;font-weight:700;margin-bottom:4px;">${escapeHtml(role)}</div>
                <div style="font-size:13px;font-weight:800;line-height:1.25;margin-bottom:6px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">
                  ${escapeHtml(it?.name || "")}
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
                  <div style="font-size:12px;color:#333;font-weight:800;">${escapeHtml(formatRub(it?.price_rub))}</div>
                  ${
                    link
                      ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer" style="font-size:12px;color:#cb11ab;font-weight:800;text-decoration:none;">На WB</a>`
                      : ""
                  }
                </div>
              </div>
            </div>
          `;
        })
        .join("");

      return `
        <div style="margin-bottom:14px;padding:12px;border:1px solid #e8e8e8;border-radius:16px;background:#fafafa;">
          <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:10px;">
            <div style="font-weight:900;font-size:14px;">${escapeHtml(title)}</div>
            <div style="font-weight:900;font-size:13px;">${escapeHtml(formatRub(total))}</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:10px;">${cardsHtml}</div>
        </div>
      `;
    })
    .join("");

  setPanelContent(blocks || `<div style="color:#666;">Ничего не найдено.</div>`);
}

async function generateCapsulesForCurrentProduct() {
  const product = getCurrentProduct();
  if (!product) {
    openPanel();
    setPanelContent(`<div style="color:#b00020;font-weight:800;">Не удалось определить товар на странице.</div>`);
    return;
  }

  const hints = getWbHints();

  openPanel();
  setPanelContent(`
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div style="font-weight:900;">Подбираем образы…</div>
      <div style="color:#666;font-size:13px;">${escapeHtml(product.name)}</div>
      <div style="height:10px;border-radius:999px;background:#f1f1f1;overflow:hidden;">
        <div style="width:60%;height:10px;background:linear-gradient(90deg,#cb11ab,#7a22ff);animation:wardrobeBar 1.1s ease-in-out infinite;"></div>
      </div>
      <style>
        @keyframes wardrobeBar { 0%{transform:translateX(-40%);} 100%{transform:translateX(110%);} }
      </style>
    </div>
  `);

  try {
    const res = await fetch(`${WARDROBE_BACKEND_BASE}/api/capsule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: product.name, nm_id: product.nm_id, product_name: product.name, ...hints }),
    });

    if (!res.ok) {
      let errMsg = "Сервер вернул ошибку";
      try {
        const j = await res.json();
        if (j?.error) errMsg = j.error;
      } catch (_) {}
      setPanelContent(
        `<div style="color:#b00020;font-weight:900;margin-bottom:8px;">Ошибка</div><div style="color:#666;font-size:13px;">${escapeHtml(
          errMsg
        )}</div>`
      );
      return;
    }

    const capsules = await res.json();
    renderCapsules(Array.isArray(capsules) ? capsules : []);
  } catch (e) {
    setPanelContent(
      `<div style="color:#b00020;font-weight:900;margin-bottom:8px;">Не удалось подключиться к backend</div>
       <div style="color:#666;font-size:13px;">Проверьте, что Flask запущен на ${escapeHtml(
         WARDROBE_BACKEND_BASE
       )} и доступен из браузера.</div>`
    );
  }
}

function getWbHints() {
  // Best-effort extraction of context from WB page.
  const norm = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();

  const crumbEls = Array.from(
    document.querySelectorAll(
      'nav a, nav span, [data-testid*="breadcrumb"] a, [data-testid*="breadcrumb"] span, .breadcrumbs a, .breadcrumbs span'
    )
  );
  const crumbsText = norm(crumbEls.map((e) => e.textContent).join(" "));

  let gender = "unisex";
  if (crumbsText.includes("женщинам")) gender = "female";
  else if (crumbsText.includes("мужчинам")) gender = "male";

  let age_group = "adult";
  if (crumbsText.includes("детям")) age_group = "child";

  // Try to read explicit "Пол" from product characteristics (more reliable than crumbs).
  try {
    const genderLabel = Array.from(document.querySelectorAll("div, span, dt"))
      .find((el) => norm(el.textContent) === "пол");
    if (genderLabel) {
      const v = norm(genderLabel.nextElementSibling?.textContent || "");
      if (v.includes("жен")) gender = "female";
      else if (v.includes("муж")) gender = "male";
    }
  } catch (_) {}

  // Season is hard to extract reliably from DOM; we leave it to backend inference.
  // Still, try a quick heuristic by scanning for the "Сезон" field nearby.
  let season = undefined;
  try {
    const seasonLabel = Array.from(document.querySelectorAll("div, span, dt"))
      .find((el) => norm(el.textContent) === "сезон");
    if (seasonLabel) {
      const v = norm(seasonLabel.nextElementSibling?.textContent || "");
      if (v.includes("зим")) season = "winter";
      else if (v.includes("лет")) season = "summer";
      else if (v.includes("вес")) season = "spring";
      else if (v.includes("осен")) season = "autumn";
      else if (v.includes("кругл") || v.includes("всесез") || v.includes("демисез")) season = "all-season";
    }
  } catch (_) {}

  const out = { gender, age_group };
  if (season) out.season = season;
  return out;
}

function createActionButtonForTitle() {
  const btn = document.createElement("button");
  btn.id = WARDROBE.buttonId;
  btn.type = "button";
  btn.textContent = "Подобрать образ";
  btn.style.cursor = "pointer";
  btn.style.padding = "6px 10px";
  btn.style.marginLeft = "8px";
  btn.style.borderRadius = "999px";
  btn.style.border = "1px solid #e8e8e8";
  btn.style.background = "#1f1f1f";
  btn.style.color = "#fff";
  btn.style.fontWeight = "700";
  btn.style.fontSize = "12px";
  btn.style.whiteSpace = "nowrap";
  btn.addEventListener("click", () => generateCapsulesForCurrentProduct());
  return btn;
}

function mountFloatingFallbackButton() {
  // Last-resort button if we can't find title area in DOM.
  if (document.getElementById(WARDROBE.buttonId)) return;
  const btn = createActionButtonForTitle();
  btn.id = WARDROBE.buttonId; // ensure exact id
  btn.style.position = "fixed";
  btn.style.top = "92px";
  btn.style.right = "16px";
  btn.style.zIndex = "2147483647";
  btn.style.boxShadow = "0 10px 22px rgba(0,0,0,0.22)";
  btn.style.padding = "10px 12px";
  btn.style.fontSize = "13px";
  document.documentElement.appendChild(btn);
}

function findBrandBadgeRowNearTitle(titleEl) {
  // On WB product pages the row with "Brand" + "Оригинал" is often right above the title.
  // Try previous siblings and small upward climb to catch that row.
  const textNorm = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();

  const candidates = [];
  if (titleEl?.previousElementSibling) candidates.push(titleEl.previousElementSibling);
  if (titleEl?.parentElement?.previousElementSibling) candidates.push(titleEl.parentElement.previousElementSibling);
  if (titleEl?.parentElement) candidates.push(titleEl.parentElement);
  if (titleEl?.parentElement?.parentElement) candidates.push(titleEl.parentElement.parentElement);

  for (const el of candidates) {
    if (!el) continue;
    const t = textNorm(el.textContent);
    if (t.includes("оригинал") || t.includes("original")) return el;
  }
  return titleEl?.parentElement || titleEl || null;
}

function mountButtonNearTitle() {
  if (document.getElementById(WARDROBE.buttonId)) return true;

  const title =
    document.querySelector('[data-testid="product-name"]') ||
    document.querySelector(".product-page__header-title") ||
    document.querySelector("h1");
  if (!title) return false;

  const row = findBrandBadgeRowNearTitle(title);
  if (!row) return false;

  // Don't mutate existing layout aggressively; wrap our button in an inline-flex container.
  const wrapper = document.createElement("span");
  wrapper.style.display = "inline-flex";
  wrapper.style.alignItems = "center";
  wrapper.style.marginLeft = "8px";

  const btn = createActionButtonForTitle();
  wrapper.appendChild(btn);
  row.appendChild(wrapper);
  return true;
}

function injectButtonIfNeeded() {
  try {
    if (!isWbProductPage()) return;
    if (document.getElementById(WARDROBE.buttonId)) return;

    const ok = mountButtonNearTitle();
    if (!ok) {
      // If title is not found (or DOM differs), still show a usable entrypoint.
      mountFloatingFallbackButton();
    }
  } catch (e) {
    // Never break the observer loop; surface error for debugging.
    console.error("[Wardrobe] injectButtonIfNeeded failed:", e);
    mountFloatingFallbackButton();
  }
}

function setupObserver() {
  // WB is SPA-ish; content loads dynamically. Observe changes and inject once.
  const obs = new MutationObserver(() => injectButtonIfNeeded());
  obs.observe(document.documentElement, { childList: true, subtree: true });
  injectButtonIfNeeded();
}

// Keep compatibility with existing popup (optional)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getProduct") {
    sendResponse(getCurrentProduct());
  }
  if (request.action === "openWardrobePanel") {
    generateCapsulesForCurrentProduct();
    sendResponse({ ok: true });
  }
});

mountDebugBadge();
setupObserver();