const state = {
  user: null,
  sessionId: null,
  page: 1,
  totalPages: 1,
  products: [],
  preferences: [],
  cart: [],
  detailOpenedAt: null,
  detailProductId: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2200);
}

function imageUrl(path) { return path || ""; }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
}

function showApp(user) {
  state.user = user;
  $("#authView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
}

function showAuth() {
  state.user = null;
  $("#appView").classList.add("hidden");
  $("#authView").classList.remove("hidden");
}

async function boot() {
  try {
    const health = await api("/agent/v1/health");
    $("#agentModel").textContent = `${health.llm.provider} · ${health.tactile_provider}`;
    const { user } = await api("/agent/v1/auth/me");
    showApp(user);
    await Promise.all([ensureSession(), loadCatalog(), loadPreferences(), loadCart()]);
  } catch (_) {
    showAuth();
  }
}

async function authenticate(path, form) {
  const body = Object.fromEntries(new FormData(form));
  try {
    const result = await api(path, { method: "POST", body: JSON.stringify(body) });
    showApp(result.user);
    state.sessionId = null;
    await Promise.all([ensureSession(), loadCatalog(), loadPreferences(), loadCart()]);
  } catch (error) {
    $("#authError").textContent = error.message;
  }
}

async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const session = await api("/agent/v1/sessions", { method: "POST", body: "{}" });
  state.sessionId = session.session_id;
  return state.sessionId;
}

async function loadCatalog(page = state.page) {
  const result = await api(`/agent/v1/products?page=${page}&page_size=30`);
  state.page = result.page;
  state.totalPages = result.total_pages;
  state.products = result.items;
  $("#catalogTitle").textContent = "모든 상품";
  $("#catalogMeta").textContent = `${result.total}개 상품 · 한 페이지 30개`;
  renderProducts(result.items);
  updatePagination();
}

function renderProducts(products, personalized = false) {
  const grid = $("#productGrid");
  grid.innerHTML = products.map((product) => {
    const reasons = product.personalization_reasons || [];
    return `<article class="product-card" data-product-id="${escapeHtml(product.product_id)}">
      <img class="product-image" src="${escapeHtml(imageUrl(product.image_url))}" alt="${escapeHtml(product.title)}" loading="lazy">
      <div class="product-body">
        <h3 class="product-title">${escapeHtml(product.title)}</h3>
        <div class="product-meta"><span>${escapeHtml(product.category)}</span><span>${product.tactile_target_source === "image_predicted" ? "이미지 기반 촉감 예상" : "리뷰+이미지 촉감"}</span></div>
        ${reasons.length ? `<p class="reason">${escapeHtml(reasons.slice(0, 2).join(" · "))}</p>` : ""}
        <div class="card-actions"><button class="view-product">상세 보기</button><button class="cart-add">장바구니</button></div>
      </div>
    </article>`;
  }).join("");
  bindProductCards();
  products.slice(0, 12).forEach((product, index) => recordEvent("product_impression", product.product_id, { rank: index + 1, personalized }).catch(() => {}));
}

function bindProductCards() {
  $$(".product-card").forEach((card) => {
    const productId = card.dataset.productId;
    card.querySelector(".view-product").addEventListener("click", () => openDetail(productId));
    card.querySelector(".cart-add").addEventListener("click", () => addCart(productId));
  });
}

function updatePagination() {
  $("#pageLabel").textContent = `${state.page} / ${state.totalPages}`;
  $("#previousPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= state.totalPages;
}

async function sendMessage(message) {
  const text = message.trim();
  if (!text) return;
  await ensureSession();
  appendMessage("user", text);
  const loading = appendMessage("assistant loading", "상품과 저장된 취향을 함께 확인하고 있습니다…");
  try {
    const result = await api(`/agent/v1/sessions/${state.sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message: text, limit: 30 }),
    });
    loading.remove();
    appendMessage("assistant", result.message);
    if (result.action === "search_products") {
      state.products = result.products;
      $("#catalogTitle").textContent = "에이전트 추천";
      $("#catalogMeta").textContent = `${result.products.length}개 · 개인화 ${result.profile_summary.personalization_applied ? "적용" : "미적용"}`;
      renderProducts(result.products, true);
      state.page = 1; state.totalPages = 1; updatePagination();
      renderIntentChips(result.intent);
      await loadPreferences();
    }
  } catch (error) {
    loading.remove();
    appendMessage("assistant", `요청을 처리하지 못했습니다: ${error.message}`);
  }
}

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const p = document.createElement("p");
  p.textContent = text;
  article.appendChild(p);
  $("#messages").appendChild(article);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return article;
}

function renderIntentChips(intent) {
  const values = [intent.category, ...(intent.desired_more || []).map(x => `${x} ↑`), ...(intent.desired_less || []).map(x => `${x} ↓`), ...(intent.avoid || []).map(x => `${x} 제외`)];
  $("#preferenceChips").innerHTML = values.filter(Boolean).map(value => `<span class="chip">${escapeHtml(value)}</span>`).join("");
}

async function openDetail(productId) {
  await recordEvent("product_click", productId, { source: "product_grid" });
  const detail = await api(`/agent/v1/products/${productId}`);
  const product = detail.product;
  const summaries = detail.tactile_summary.summary || [];
  const concerns = detail.tactile_concerns.concerns || [];
  const related = detail.related || {};
  const relatedCards = (items, kind) => items.length ? `<div class="related-list">${items.slice(0, 6).map(item => `<button class="related-card" data-related-id="${escapeHtml(item.product_id)}" data-related-kind="${kind}">
    <img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}"><span>${escapeHtml(item.title)}</span>
    <small>${kind === "design" ? "디자인" : "촉감"} 유사도 ${Number(item.relevance_score).toFixed(2)}</small>
  </button>`).join("")}</div>` : `<p class="muted">표시할 유사 상품이 없습니다.</p>`;
  $("#detailContent").innerHTML = `<div class="detail-top">
    <img src="${escapeHtml(product.image_url)}" alt="${escapeHtml(product.title)}">
    <div><p class="eyebrow">${escapeHtml(product.category)}</p><h2>${escapeHtml(product.title)}</h2>
    <p>${product.tactile_target_source === "image_predicted" ? "리뷰가 없어 이미지로 촉감을 예상했습니다. 구매자 의견으로 해석하지 않습니다." : `리뷰 ${product.reviewer_count}명 · claim ${product.claim_count}개`}</p>
    <button class="primary" id="detailCartAdd">장바구니에 담기</button></div></div>
    <h3>구매자들이 말하는 소재</h3>
    ${summaries.length ? summaries.slice(0, 8).map(item => `<section><strong>${escapeHtml(item.display_text)}</strong>${(item.evidence_details || []).slice(0, 2).map(ev => `<p class="evidence">“${escapeHtml(ev.original_span)}”</p>`).join("")}</section>`).join("") : `<p class="muted">${escapeHtml(detail.tactile_summary.message)}</p>`}
    <h3>소재 관련 의견</h3>
    ${concerns.length ? concerns.map(item => `<p><strong>${escapeHtml(item.label)}</strong> · ${item.reviewer_count}명의 독립 구매자 근거</p>`).join("") : `<p class="muted">반복적으로 확인된 소재 우려가 없습니다.</p>`}
    <h3>디자인이 비슷한 상품</h3>
    ${relatedCards(related.design_similar || [], "design")}
    <h3>촉감이 비슷한 상품</h3>
    <p class="muted">리뷰와 이미지로 만든 촉감 target을 사용하며, 리뷰가 없는 상품은 이미지 기반 예상임을 구분합니다.</p>
    ${relatedCards(related.tactile_similar || [], "tactile")}`;
  $("#detailCartAdd").addEventListener("click", () => addCart(productId));
  $$("[data-related-id]").forEach(button => button.addEventListener("click", async () => {
    await recordEvent("similar_product_click", button.dataset.relatedId, {
      anchor_product_id: productId,
      similarity_type: button.dataset.relatedKind,
    });
    await openDetail(button.dataset.relatedId);
  }));
  state.detailOpenedAt = performance.now();
  state.detailProductId = productId;
  if (!$("#detailDialog").open) $("#detailDialog").showModal();
}

async function recordEvent(eventType, productId, context = {}) {
  if (!state.user) return;
  return api("/agent/v1/events", { method: "POST", body: JSON.stringify({ event_type: eventType, product_id: productId, session_id: state.sessionId, context }) });
}

async function addCart(productId) {
  await api("/agent/v1/cart/items", { method: "POST", body: JSON.stringify({ product_id: productId, quantity: 1, session_id: state.sessionId }) });
  toast("장바구니에 담았습니다.");
  await loadCart();
}

async function loadCart() {
  const result = await api("/agent/v1/cart");
  state.cart = result.items;
  $("#cartCount").textContent = result.items.length;
  $("#cartItems").innerHTML = result.items.length ? result.items.map(item => `<article class="cart-row">
    <img src="${escapeHtml(item.product.image_url)}" alt=""><div><strong>${escapeHtml(item.product.title)}</strong><small>수량 ${item.quantity}</small></div>
    <button class="remove" data-remove-cart="${escapeHtml(item.product_id)}">삭제</button></article>`).join("") : `<p class="muted">장바구니가 비어 있습니다.</p>`;
  $$('[data-remove-cart]').forEach(button => button.addEventListener("click", async () => {
    await api(`/agent/v1/cart/items/${button.dataset.removeCart}`, { method: "DELETE" });
    await loadCart();
  }));
}

async function loadPreferences() {
  const result = await api("/agent/v1/preferences");
  state.preferences = result.items;
  $("#preferenceCount").textContent = result.items.length;
  $("#preferenceItems").innerHTML = result.items.length ? result.items.map(item => `<article class="preference-row">
    <div><strong>${escapeHtml(item.attribute)}</strong><small>${escapeHtml(item.scope_category || "전체")} · ${escapeHtml(item.direction)} · confidence ${Number(item.confidence).toFixed(2)}</small></div>
    <span class="chip">${escapeHtml(item.attribute_type)}</span><button class="remove" data-forget="${escapeHtml(item.preference_id)}">잊기</button></article>`).join("") : `<p class="muted">아직 저장된 취향이 없습니다.</p>`;
  $$('[data-forget]').forEach(button => button.addEventListener("click", async () => {
    await api(`/agent/v1/preferences/${button.dataset.forget}`, { method: "DELETE" });
    await loadPreferences(); toast("취향을 삭제했습니다.");
  }));
}

$$('[data-auth-tab]').forEach(button => button.addEventListener("click", () => {
  $$('[data-auth-tab]').forEach(x => x.classList.toggle("active", x === button));
  $("#loginForm").classList.toggle("hidden", button.dataset.authTab !== "login");
  $("#registerForm").classList.toggle("hidden", button.dataset.authTab !== "register");
  $("#authError").textContent = "";
}));
$("#loginForm").addEventListener("submit", (event) => { event.preventDefault(); authenticate("/agent/v1/auth/login", event.currentTarget); });
$("#registerForm").addEventListener("submit", (event) => { event.preventDefault(); authenticate("/agent/v1/auth/register", event.currentTarget); });
$("#logoutButton").addEventListener("click", async () => { await api("/agent/v1/auth/logout", { method: "POST", body: "{}" }); showAuth(); });
$("#chatForm").addEventListener("submit", (event) => { event.preventDefault(); const input = $("#promptInput"); const text = input.value; input.value = ""; sendMessage(text); });
$("#messages").addEventListener("click", (event) => { if (event.target.matches(".suggestions button")) sendMessage(event.target.textContent); });
$("#previousPage").addEventListener("click", () => loadCatalog(state.page - 1));
$("#nextPage").addEventListener("click", () => loadCatalog(state.page + 1));
$("#brandButton").addEventListener("click", () => { state.page = 1; loadCatalog(1); });
$("#cartButton").addEventListener("click", async () => { await loadCart(); $("#cartDialog").showModal(); });
$("#preferencesButton").addEventListener("click", async () => { await loadPreferences(); $("#preferencesDialog").showModal(); });
$("#openChatButton").addEventListener("click", () => $("#agentPanel").classList.add("open"));
$("#closeChatButton").addEventListener("click", () => $("#agentPanel").classList.remove("open"));
$$('[data-close]').forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
$("#detailDialog").addEventListener("close", () => {
  if (state.detailOpenedAt && state.detailProductId) {
    const dwellMs = Math.min(300000, Math.round(performance.now() - state.detailOpenedAt));
    recordEvent("product_dwell", state.detailProductId, { dwell_ms: dwellMs, page_active: !document.hidden }).catch(() => {});
  }
  state.detailOpenedAt = null; state.detailProductId = null;
});

boot();
