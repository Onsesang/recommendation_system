"use strict";

const state = { page: 1, totalPages: 1, queryText: null, items: [], current: null };
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function post(path, payload) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 3200);
}

function loading(active) { $("loading").hidden = !active; }

function showEvidence(items) {
  $("dialogEvidence").innerHTML = items.length ? items.map((row) => `
    <div class="quote">“${escapeHtml(row.original_span || row.claim)}”
      <div class="meta">review ${escapeHtml(row.review_id)} · ${escapeHtml(row.source)} · confidence ${Number(row.confidence).toFixed(2)}</div>
    </div>`).join("") : "<p>표시할 근거가 없습니다.</p>";
  $("evidenceDialog").showModal();
}

function evidenceButton(items, label = "실제 리뷰 보기") {
  const button = document.createElement("button");
  button.className = "evidence-button";
  button.textContent = label;
  button.addEventListener("click", () => showEvidence(items));
  return button;
}

function productCard(item) {
  const card = document.createElement("article");
  card.className = "catalog-card";
  card.tabIndex = 0;
  const matched = item.matched_tactile_constraints?.length
    ? `<div class="match">조건 일치: ${escapeHtml(item.matched_tactile_constraints.join(", "))}</div>` : "";
  const source = item.tactile_target_source === "image_predicted"
    ? '<span class="source-badge predicted">이미지 기반 촉감 예상</span>'
    : item.tactile_target_source === "review_image_blended"
      ? '<span class="source-badge blended">리뷰+이미지 촉감</span>' : "";
  card.innerHTML = `
    <div class="catalog-image"><img loading="lazy" src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}"></div>
    <div class="catalog-body"><span class="pill">${escapeHtml(item.category)}</span>
      <h3>${escapeHtml(item.title || item.product_id)}</h3>${source}${matched}
      <div class="catalog-meta">구매자 ${item.reviewer_count}명 · claim ${item.claim_count}개</div>
    </div>`;
  const open = () => openProduct(item.product_id);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return card;
}

function renderPagination(data) {
  const root = $("pagination"); root.innerHTML = "";
  const add = (label, page, disabled = false, active = false) => {
    const button = document.createElement("button"); button.textContent = label; button.disabled = disabled; button.classList.toggle("active", active);
    button.addEventListener("click", () => loadPage(page)); root.appendChild(button);
  };
  add("이전", data.page - 1, !data.has_previous);
  const start = Math.max(1, data.page - 2); const end = Math.min(data.total_pages, start + 4);
  for (let page = Math.max(1, end - 4); page <= end; page += 1) add(String(page), page, false, page === data.page);
  add("다음", data.page + 1, !data.has_next);
}

function renderCatalog(data) {
  state.page = data.page; state.totalPages = data.total_pages; state.items = data.items;
  $("catalogGrid").innerHTML = ""; data.items.forEach((item) => $("catalogGrid").appendChild(productCard(item)));
  $("resultCount").textContent = `${data.total.toLocaleString()}개 · ${data.page}/${data.total_pages} 페이지`;
  $("catalogEyebrow").textContent = data.mode === "natural_language_search" ? "NATURAL LANGUAGE RESULTS" : "ALL PRODUCTS";
  $("catalogTitle").textContent = data.mode === "natural_language_search" ? `“${data.query_text}” 검색 결과` : "모든 상품";
  $("catalogMessage").textContent = data.message || "한 화면에 30개 상품을 보여줍니다.";
  $("clearSearch").hidden = data.mode !== "natural_language_search";
  renderPagination(data);
}

async function loadPage(page = 1) {
  loading(true);
  try {
    const data = state.queryText
      ? await post("/v1/products/search", { query_text: state.queryText, page, page_size: 30 })
      : await api(`/v1/products?page=${page}&page_size=30`);
    showCatalog(); renderCatalog(data); window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) { toast(error.message); } finally { loading(false); }
}

function showCatalog() { $("catalogScreen").hidden = false; $("detailScreen").hidden = true; }
function showDetail() { $("catalogScreen").hidden = true; $("detailScreen").hidden = false; }

function renderSummary(data) {
  const root = $("summary"); root.innerHTML = "";
  if (data.status !== "available") { root.innerHTML = `<div class="empty">${escapeHtml(data.message)}</div>`; return; }
  data.summary.slice(0, 12).forEach((item) => {
    const card = document.createElement("div"); card.className = `evidence-card${item.contradictory ? " warning" : ""}`;
    card.innerHTML = `<span class="tag">${escapeHtml(item.display_label)}</span><h3>${escapeHtml(item.display_text)}</h3><div class="meta">구매자 ${item.reviewer_count}명 · 신뢰도 ${item.confidence.toFixed(2)}</div>`;
    card.appendChild(evidenceButton(item.evidence_details)); root.appendChild(card);
  });
}

function renderConcerns(data) {
  const root = $("concerns"); root.innerHTML = "";
  if (!data.concerns.length) { root.innerHTML = `<div class="empty">${data.status === "insufficient_evidence" ? "아직 충분한 소재 관련 리뷰가 없습니다." : "반복적으로 확인된 소재 우려가 없습니다."}</div>`; return; }
  data.concerns.forEach((item) => {
    const card = document.createElement("div"); card.className = "evidence-card warning";
    card.innerHTML = `<span class="tag">${escapeHtml(item.severity)}</span><h3>${escapeHtml(item.label)} 관련 부정적 의견</h3><div class="meta">구매자 ${item.reviewer_count}명 · 부정 비율 ${(item.negative_ratio * 100).toFixed(0)}%</div>`;
    card.appendChild(evidenceButton(item.evidence));
    if (item.alternative_action) {
      const button = document.createElement("button"); button.className = "secondary"; button.textContent = `${item.alternative_action.desired_direction === "less" ? "덜" : "더"} ${item.label} 상품 보기`;
      button.addEventListener("click", () => loadAlternatives(state.current, item.alternative_action.desired_direction, item.property)); card.appendChild(button);
    }
    root.appendChild(card);
  });
}

function relatedCard(item, kind) {
  const card = document.createElement("article"); card.className = "related-card";
  const score = kind === "design"
    ? `디자인 관련도 ${item.relevance_score.toFixed(2)}`
    : `촉감 관련도 ${item.relevance_score.toFixed(2)}`;
  const imageUrl = item.image_url || `/images/${item.product_id}.jpg`;
  const source = kind === "tactile"
    ? item.target_source === "image_predicted"
      ? '<span class="source-badge predicted">이미지 기반 예상</span>'
      : '<span class="source-badge blended">리뷰+이미지</span>'
    : '<span class="source-badge visual">FashionCLIP 이미지</span>';
  const detail = kind === "design"
    ? `이미지 ${Number(item.score_breakdown?.image_similarity_01 || 0).toFixed(2)} · 제목 ${Number(item.title_style_similarity || 0).toFixed(2)}`
    : `confidence ${Number(item.evidence_strength || 0).toFixed(2)}`;
  card.innerHTML = `<img loading="lazy" src="${escapeHtml(imageUrl)}" alt="${escapeHtml(item.title)}"><div><span class="pill">${escapeHtml(item.category)}</span><h3>${escapeHtml(item.title || item.product_id)}</h3>${source}<div class="score">${score}</div><div class="meta">${detail}</div></div>`;
  card.addEventListener("click", () => openProduct(item.product_id)); return card;
}

function renderRelated(data) {
  $("designMethod").textContent = data.design_method_note;
  $("tactileMethod").textContent = data.tactile_method_note;
  const target = data.anchor_target;
  if (target) {
    const predicted = target.tactile_target_source === "image_predicted";
    const label = predicted ? "이미지 기반 촉감 예상" : "리뷰+이미지 촉감";
    $("productTargetInfo").innerHTML = `<span class="source-badge ${predicted ? "predicted" : "blended"}">${label}</span><span>리뷰 ${(target.review_weight * 100).toFixed(0)}% · 이미지 ${(target.image_weight * 100).toFixed(0)}% · confidence ${target.tactile_target_confidence.toFixed(2)}</span>`;
  } else { $("productTargetInfo").innerHTML = ""; }
  $("designRelated").innerHTML = ""; data.design_similar.forEach((item) => $("designRelated").appendChild(relatedCard(item, "design")));
  $("tactileRelated").innerHTML = ""; data.tactile_similar.forEach((item) => $("tactileRelated").appendChild(relatedCard(item, "tactile")));
  if (!data.tactile_similar.length) $("tactileRelated").innerHTML = '<div class="empty">비교할 촉감 근거가 없습니다.</div>';
}

async function openProduct(asin) {
  loading(true);
  try {
    const [profile, summary, concerns, related] = await Promise.all([
      api(`/v1/products/${asin}/tactile?include_claims=false`),
      api(`/v1/products/${asin}/tactile-summary`),
      api(`/v1/products/${asin}/tactile-concerns`),
      api(`/v1/products/${asin}/related?limit=10`),
    ]);
    state.current = asin; showDetail(); $("alternativeSection").hidden = true;
    $("productTitle").textContent = profile.title || asin; $("productCategory").textContent = profile.category; $("productAsin").textContent = asin;
    $("productStats").textContent = `구매자 ${profile.reviewer_count}명 · 리뷰 ${profile.review_count}개 · 소재 claim ${profile.claim_count}개`;
    $("productImage").src = `/images/${asin}.jpg`; $("productImage").alt = profile.title || asin;
    renderSummary(summary); renderConcerns(concerns); renderRelated(related); window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) { toast(error.message); } finally { loading(false); }
}

async function loadAlternatives(anchor, direction, concept) {
  loading(true);
  try {
    const data = await post("/v1/recommendations/tactile-alternatives", { anchor_product_id: anchor, direction, tactile_concept: concept, top_k: 10 });
    $("alternativeSection").hidden = false; $("alternativeTitle").textContent = `${direction === "less" ? "덜" : "더"} ${concept} 상품`;
    $("alternatives").innerHTML = ""; data.results.forEach((item) => $("alternatives").appendChild(relatedCard(item, "tactile")));
    if (!data.results.length) $("alternatives").innerHTML = `<div class="empty">${escapeHtml(data.message)}</div>`;
    $("alternativeSection").scrollIntoView({ behavior: "smooth" });
  } catch (error) { toast(error.message); } finally { loading(false); }
}

async function submitPrompt(event) {
  event.preventDefault(); const value = $("promptInput").value.trim(); if (!value) return;
  state.queryText = value; await loadPage(1);
}

window.addEventListener("DOMContentLoaded", async () => {
  $("promptForm").addEventListener("submit", submitPrompt);
  $("clearSearch").addEventListener("click", async () => { state.queryText = null; $("promptInput").value = ""; await loadPage(1); });
  $("backToCatalog").addEventListener("click", () => { showCatalog(); window.scrollTo({ top: 0, behavior: "smooth" }); });
  $("closeDialog").addEventListener("click", () => $("evidenceDialog").close());
  try {
    const health = await api("/v1/tactile/health"); $("health").textContent = `${health.source_products}개 상품 · ${health.accepted_claims.toLocaleString()}개 리뷰 claim`;
    await loadPage(1);
  } catch (error) { toast(error.message); $("health").textContent = "연결 실패"; }
});
