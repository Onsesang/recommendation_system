"use strict";

const state = { items: [], annotations: {}, missingSpans: {}, reviewChecks: {}, filteredIndices: [], currentIndex: 0, filter: "all", saving: false, editForceAdvance: false, editingMissingId: null, selectedReviewText: "", selectedReviewId: null };
const $ = (id) => document.getElementById(id);
const elements = {};
const scopes = ["main_fabric", "lining", "component", "whole_garment", "outer_surface", "unknown"];
const propertyStatuses = ["present", "absent", "uncertain", "comparative", "mixed"];
const intensities = ["none", "slight", "moderate", "strong", "unknown"];
const sentiments = ["positive", "negative", "neutral", "mixed", "unknown"];
const evidenceBases = ["direct_touch", "worn_experience", "visual_only", "product_behavior", "unspecified"];
const observabilities = ["low", "medium", "high", "unknown"];

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function highlightedReview(review, quote, siblingQuotes = [], missingQuotes = []) {
  const candidates = [
    { quote, kind: "extracted" },
    ...siblingQuotes.filter((value) => value !== quote).map((value) => ({ quote: value, kind: "sibling" })),
    ...missingQuotes.map((value) => ({ quote: value, kind: "missing" })),
  ];
  const intervals = [];
  candidates.forEach((candidate) => {
    const start = review.indexOf(candidate.quote);
    if (start >= 0) intervals.push({ ...candidate, start, end: start + candidate.quote.length });
  });
  const priority = { extracted: 0, sibling: 1, missing: 2 };
  intervals.sort((left, right) => left.start - right.start || priority[left.kind] - priority[right.kind]);
  let cursor = 0;
  let html = "";
  intervals.forEach((interval) => {
    if (interval.start < cursor) return;
    html += escapeHtml(review.slice(cursor, interval.start));
    const className = interval.kind === "missing" ? ' class="missing-highlight"' : interval.kind === "sibling" ? ' class="sibling-highlight"' : "";
    html += `<mark${className}>${escapeHtml(review.slice(interval.start, interval.end))}</mark>`;
    cursor = interval.end;
  });
  return html + escapeHtml(review.slice(cursor));
}

function annotationFor(item) { return state.annotations[item.span_id] || null; }
function statusFor(item) { return annotationFor(item)?.action || "unreviewed"; }
function currentItem() { return state.items[state.currentIndex]; }
function missingForReview(reviewId) { return Object.values(state.missingSpans).filter((record) => record.review_id === reviewId); }
function setOptions(select, values) { select.innerHTML = values.map((value) => `<option value="${value}">${value}</option>`).join(""); }

function updateFilteredIndices() {
  state.filteredIndices = state.items.map((_, index) => index).filter((index) => {
    const status = statusFor(state.items[index]);
    if (state.filter === "all") return true;
    if (state.filter === "unreviewed") return status === "unreviewed";
    if (state.filter === "new_v2") {
      const sources = state.items[index].extraction_sources || [];
      return sources.length > 0 && !sources.includes("v1");
    }
    return status === state.filter;
  });
}

function currentFilteredPosition() { return state.filteredIndices.indexOf(state.currentIndex); }
function nearestFilteredIndex() {
  if (!state.filteredIndices.length) return null;
  if (currentFilteredPosition() >= 0) return state.currentIndex;
  return state.filteredIndices.find((index) => index > state.currentIndex) ?? state.filteredIndices.at(-1);
}

function updateCounts() {
  const counts = { good: 0, bad: 0, edit: 0 };
  Object.values(state.annotations).forEach((annotation) => { if (counts[annotation.action] !== undefined) counts[annotation.action] += 1; });
  const reviewed = Object.keys(state.annotations).length;
  const total = state.items.length;
  const percent = total ? Math.round((reviewed / total) * 100) : 0;
  elements.progressText.textContent = `${reviewed} / ${total} reviewed`;
  elements.progressPercent.textContent = `${percent}%`;
  elements.progressBar.style.width = `${percent}%`;
  elements.allCount.textContent = total;
  elements.unreviewedCount.textContent = total - reviewed;
  elements.goodCount.textContent = counts.good;
  elements.badCount.textContent = counts.bad;
  elements.editCount.textContent = counts.edit;
  elements.newV2Count.textContent = state.items.filter((item) => {
    const sources = item.extraction_sources || [];
    return sources.length > 0 && !sources.includes("v1");
  }).length;
}

function metadataHtml(qwen, extractionSources = []) {
  const entries = [["Scope", qwen.scope || "—"], ["Property", qwen.property_status || "—"], ["Intensity", qwen.intensity || "—"], ["Sentiment", qwen.sentiment || "—"], ["Evidence", qwen.evidence_basis || "—"], ["Visual", qwen.visual_observability || "—"], ["Extraction", extractionSources.length ? extractionSources.join(" + ") : "v1"]];
  return entries.map(([label, value]) => `<div class="metadata-pair"><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
}

function renderMissingAudit(item) {
  const records = missingForReview(item.review_id).sort((left, right) => left.created_at.localeCompare(right.created_at));
  if (!records.length) {
    elements.missingSpanList.innerHTML = '<p class="missing-empty">등록된 누락 span이 없습니다.</p>';
  } else {
    elements.missingSpanList.innerHTML = records.map((record) => `
      <article class="missing-span-card">
        <div class="missing-span-copy">
          <blockquote>${escapeHtml(record.quote)}</blockquote>
          <p>${escapeHtml(record.claim)}</p>
          <small>${escapeHtml(record.scope)} · ${escapeHtml(record.property_status)} · ${escapeHtml(record.intensity)} · visual ${escapeHtml(record.visual_observability)}</small>
        </div>
        <div class="missing-span-actions">
          <button type="button" data-missing-action="edit" data-missing-id="${record.missing_span_id}">Edit</button>
          <button type="button" class="delete-missing" data-missing-action="delete" data-missing-id="${record.missing_span_id}">Delete</button>
        </div>
      </article>`).join("");
  }
  const candidates = state.items.filter((candidate) => candidate.review_id === item.review_id);
  const labeled = candidates.filter((candidate) => annotationFor(candidate)).length;
  const check = state.reviewChecks[item.review_id];
  elements.recallCheckStatus.textContent = check ? "FULL REVIEW CHECKED" : "FULL REVIEW NOT CHECKED";
  elements.recallCheckStatus.className = check ? "recall-complete" : "";
  elements.recallCheckDetail.textContent = `${labeled}/${candidates.length} extracted candidates judged · ${records.length} missing added`;
  elements.toggleRecallCheck.textContent = check ? "Unmark review check" : "Mark full review checked";
  elements.toggleRecallCheck.classList.toggle("checked", Boolean(check));
}

function renderSiblingSpans(item) {
  const siblings = state.items.filter((candidate) => candidate.review_id === item.review_id);
  const reviewed = siblings.filter((candidate) => annotationFor(candidate)).length;
  elements.siblingSummary.textContent = `${reviewed}/${siblings.length} judged`;
  elements.siblingSpanList.innerHTML = siblings.map((candidate) => {
    const current = candidate.span_id === item.span_id;
    const status = statusFor(candidate);
    return `<button type="button" class="sibling-span ${current ? "current" : ""}" data-sibling-span-id="${candidate.span_id}">
      <span class="sibling-number">${candidate.index + 1}</span>
      <span class="sibling-quote">${escapeHtml(candidate.quote)}</span>
      <span class="sibling-model ${candidate.qwen.accepted ? "accepted" : "rejected"}">${candidate.qwen.accepted ? "QWEN ACCEPT" : "QWEN REJECT"}</span>
      <span class="sibling-human ${status}">${status.toUpperCase()}</span>
    </button>`;
  }).join("");
}

function render() {
  updateFilteredIndices();
  updateCounts();
  const fallbackIndex = nearestFilteredIndex();
  if (fallbackIndex === null) {
    elements.auditCard.classList.add("hidden");
    elements.emptyState.classList.remove("hidden");
    elements.previousButton.disabled = true;
    elements.nextButton.disabled = true;
    return;
  }
  state.currentIndex = fallbackIndex;
  elements.auditCard.classList.remove("hidden");
  elements.emptyState.classList.add("hidden");

  const item = currentItem();
  const annotation = annotationFor(item);
  const status = statusFor(item);
  const filteredPosition = currentFilteredPosition();
  elements.productAsin.textContent = item.asin;
  elements.productTitle.textContent = item.product_title || "Product image";
  elements.imageQuality.textContent = item.image.local ? "ORIGINAL" : "SOURCE UNAVAILABLE";
  elements.productImage.src = item.image.api_url;
  elements.productImage.onerror = () => {
    if (item.image.remote_url && elements.productImage.src !== item.image.remote_url) {
      elements.productImage.src = item.image.remote_url;
      elements.imageQuality.textContent = "REMOTE SOURCE";
    }
  };
  elements.positionLabel.textContent = `ITEM ${state.currentIndex + 1} OF ${state.items.length}`;
  elements.quoteText.textContent = item.quote;
  const missingRecords = missingForReview(item.review_id);
  const siblingQuotes = state.items.filter((candidate) => candidate.review_id === item.review_id).map((candidate) => candidate.quote);
  elements.reviewText.innerHTML = highlightedReview(item.review, item.quote, siblingQuotes, missingRecords.map((record) => record.quote));
  renderSiblingSpans(item);
  renderMissingAudit(item);
  elements.qwenDecision.textContent = item.qwen.accepted ? "ACCEPTED" : "REJECTED";
  elements.qwenDecision.className = `model-decision ${item.qwen.accepted ? "accepted" : "rejected"}`;
  elements.qwenClaim.textContent = item.qwen.claim || "No normalized claim";
  elements.qwenMetadata.innerHTML = metadataHtml(item.qwen, item.extraction_sources || []);
  elements.qwenReason.textContent = item.qwen.rejection_reason || "";
  elements.qwenReason.classList.toggle("hidden", !item.qwen.rejection_reason);

  elements.reviewStatus.textContent = status.toUpperCase();
  elements.reviewStatus.className = `review-status ${status}`;
  elements.resetButton.classList.toggle("hidden", !annotation);
  elements.savedSummary.classList.toggle("hidden", !annotation);
  if (annotation) {
    const decision = annotation.human_accepted ? "Accepted" : "Rejected";
    const detail = annotation.human_accepted ? `${annotation.human_scope} · ${annotation.human_property_status} · visual ${annotation.human_visual_observability}` : "Marked as not valid material evidence";
    elements.savedSummary.innerHTML = `<strong>Human: ${decision}</strong><br>${escapeHtml(detail)}${annotation.comment ? `<br><span>${escapeHtml(annotation.comment)}</span>` : ""}<br><small>${escapeHtml(annotation.annotator_id)} · ${new Date(annotation.updated_at).toLocaleString()}</small>`;
  }

  elements.jumpInput.value = state.currentIndex + 1;
  elements.itemTotal.textContent = `/ ${state.items.length}`;
  elements.previousButton.disabled = filteredPosition <= 0;
  elements.nextButton.disabled = filteredPosition >= state.filteredIndices.length - 1;
}

function navigate(delta) {
  if (!state.filteredIndices.length) return;
  const position = currentFilteredPosition();
  const target = Math.max(0, Math.min(state.filteredIndices.length - 1, position + delta));
  if (target === position) return;
  state.currentIndex = state.filteredIndices[target];
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function annotatorId() { return elements.annotatorInput.value.trim(); }
function ensureAnnotator() {
  if (annotatorId()) return true;
  elements.annotatorInput.focus();
  showToast("먼저 Annotator 이름을 입력해 주세요.", true);
  return false;
}

function showToast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.style.background = isError ? "#8f3333" : "#18201d";
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => elements.toast.classList.remove("visible"), 1800);
}

async function saveAnnotation(payload, { forceAdvance = false } = {}) {
  if (state.saving || !ensureAnnotator()) return;
  state.saving = true;
  const item = currentItem();
  const previousPosition = currentFilteredPosition();
  elements.saveMessage.textContent = "Saving…";
  try {
    const response = await fetch(`/api/annotations/${item.span_id}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, annotator_id: annotatorId() }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Save failed");
    state.annotations[item.span_id] = result.annotation;
    localStorage.setItem("materialAuditAnnotator", annotatorId());
    elements.saveMessage.textContent = "Saved";
    showToast(`${payload.action.toUpperCase()} 저장 완료`);
    updateFilteredIndices();
    if (forceAdvance || elements.autoAdvance.checked) {
      const candidates = state.filteredIndices;
      if (state.filter === "unreviewed") state.currentIndex = candidates[previousPosition] ?? candidates.at(-1) ?? state.currentIndex;
      else {
        const position = candidates.indexOf(state.currentIndex);
        state.currentIndex = candidates[Math.min(position + 1, candidates.length - 1)] ?? state.currentIndex;
      }
    }
    render();
  } catch (error) {
    elements.saveMessage.textContent = "Save failed";
    showToast(error.message, true);
  } finally {
    state.saving = false;
    setTimeout(() => { elements.saveMessage.textContent = ""; }, 1800);
  }
}

function markGood({ forceAdvance = false } = {}) {
  const item = currentItem();
  if (!item.qwen.accepted) {
    showToast("기각된 span을 승인하려면 normalized fields를 입력해 주세요.");
    openEdit(true, forceAdvance);
    return;
  }
  saveAnnotation({ action: "good", human_accepted: true, human_claim: item.qwen.claim, human_scope: item.qwen.scope, human_property_status: item.qwen.property_status, human_visual_observability: item.qwen.visual_observability, comment: "" }, { forceAdvance });
}

function markGoodAndNext() {
  markGood({ forceAdvance: true });
}

function markBad() {
  saveAnnotation({ action: "bad", human_accepted: false, human_claim: "", human_scope: "", human_property_status: "", human_visual_observability: "", comment: "" });
}

function openEdit(forceAccepted = null, forceAdvance = false) {
  if (!ensureAnnotator()) return;
  const item = currentItem();
  const annotation = annotationFor(item);
  state.editForceAdvance = forceAdvance;
  const accepted = forceAccepted ?? annotation?.human_accepted ?? item.qwen.accepted;
  elements.editAccepted.value = String(accepted);
  elements.editClaim.value = annotation?.human_claim || item.qwen.claim || "";
  const scope = annotation?.human_scope || item.qwen.scope;
  const propertyStatus = annotation?.human_property_status || item.qwen.property_status;
  const observability = annotation?.human_visual_observability || item.qwen.visual_observability;
  elements.editScope.value = scopes.includes(scope) ? scope : scopes[0];
  elements.editPropertyStatus.value = propertyStatuses.includes(propertyStatus) ? propertyStatus : propertyStatuses[0];
  elements.editObservability.value = observabilities.includes(observability) ? observability : observabilities[0];
  elements.editComment.value = annotation?.comment || "";
  toggleAcceptedFields();
  elements.editDialog.showModal();
}

function toggleAcceptedFields() {
  const accepted = elements.editAccepted.value === "true";
  document.querySelectorAll(".accepted-only").forEach((field) => field.classList.toggle("hidden", !accepted));
}

async function resetAnnotation() {
  const item = currentItem();
  if (!annotationFor(item) || state.saving) return;
  state.saving = true;
  try {
    const response = await fetch(`/api/annotations/${item.span_id}`, { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Reset failed");
    delete state.annotations[item.span_id];
    showToast("검수 결과를 초기화했습니다.");
    render();
  } catch (error) { showToast(error.message, true); }
  finally { state.saving = false; }
}

function selectedTextFromReview() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.anchorNode || !elements.reviewText.contains(selection.anchorNode)) return "";
  const selected = selection.toString().trim();
  return currentItem().review.includes(selected) ? selected : "";
}

function openMissing(record = null) {
  if (!ensureAnnotator()) return;
  state.editingMissingId = record?.missing_span_id || null;
  elements.missingDialogTitle.textContent = record ? "Edit missing span" : "Add missing span";
  const selectedQuote = state.selectedReviewId === currentItem().review_id ? state.selectedReviewText : "";
  elements.missingQuote.value = record?.quote || selectedQuote;
  elements.missingClaim.value = record?.claim || "";
  elements.missingScope.value = record?.scope || "main_fabric";
  elements.missingPropertyStatus.value = record?.property_status || "present";
  elements.missingIntensity.value = record?.intensity || "unknown";
  elements.missingSentiment.value = record?.sentiment || "neutral";
  elements.missingEvidence.value = record?.evidence_basis || "unspecified";
  elements.missingObservability.value = record?.visual_observability || "unknown";
  elements.missingComment.value = record?.comment || "";
  elements.missingDialog.showModal();
  if (!elements.missingQuote.value) elements.missingQuote.focus();
}

async function saveMissingSpan() {
  if (state.saving || !ensureAnnotator()) return;
  state.saving = true;
  const editingId = state.editingMissingId;
  const payload = {
    source_span_id: currentItem().span_id,
    quote: elements.missingQuote.value,
    claim: elements.missingClaim.value,
    scope: elements.missingScope.value,
    property_status: elements.missingPropertyStatus.value,
    intensity: elements.missingIntensity.value,
    sentiment: elements.missingSentiment.value,
    evidence_basis: elements.missingEvidence.value,
    visual_observability: elements.missingObservability.value,
    annotator_id: annotatorId(),
    comment: elements.missingComment.value,
  };
  try {
    const response = await fetch(editingId ? `/api/missing-spans/${editingId}` : "/api/missing-spans", {
      method: editingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Missing span save failed");
    state.missingSpans[result.missing_span.missing_span_id] = result.missing_span;
    localStorage.setItem("materialAuditAnnotator", annotatorId());
    elements.missingDialog.close();
    state.editingMissingId = null;
    state.selectedReviewText = "";
    state.selectedReviewId = null;
    showToast(editingId ? "누락 span을 수정했습니다." : "누락 span을 추가했습니다.");
    render();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.saving = false;
  }
}

async function deleteMissingSpan(missingSpanId) {
  const record = state.missingSpans[missingSpanId];
  if (!record || state.saving || !window.confirm(`이 누락 span을 삭제할까요?\n\n${record.quote}`)) return;
  state.saving = true;
  try {
    const response = await fetch(`/api/missing-spans/${missingSpanId}`, { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Delete failed");
    delete state.missingSpans[missingSpanId];
    showToast("누락 span을 삭제했습니다.");
    render();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.saving = false;
  }
}

async function toggleReviewCheck() {
  if (state.saving || !ensureAnnotator()) return;
  state.saving = true;
  const reviewId = currentItem().review_id;
  const checked = Boolean(state.reviewChecks[reviewId]);
  try {
    const response = await fetch(`/api/review-checks/${reviewId}`, checked ? { method: "DELETE" } : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ annotator_id: annotatorId() }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Review check save failed");
    if (checked) delete state.reviewChecks[reviewId];
    else state.reviewChecks[reviewId] = result.review_check;
    showToast(checked ? "Full review check를 해제했습니다." : "Full review 확인 완료로 저장했습니다.");
    render();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.saving = false;
  }
}

function bindEvents() {
  elements.previousButton.addEventListener("click", () => navigate(-1));
  elements.nextButton.addEventListener("click", markGoodAndNext);
  elements.goodButton.addEventListener("click", () => markGood());
  elements.badButton.addEventListener("click", markBad);
  elements.editButton.addEventListener("click", () => openEdit());
  elements.resetButton.addEventListener("click", resetAnnotation);
  elements.addMissingButton.addEventListener("click", () => openMissing());
  elements.toggleRecallCheck.addEventListener("click", toggleReviewCheck);
  elements.reviewText.addEventListener("mouseup", () => {
    const selected = selectedTextFromReview();
    if (selected) {
      state.selectedReviewText = selected;
      state.selectedReviewId = currentItem().review_id;
    }
  });
  elements.missingSpanList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-missing-action]");
    if (!button) return;
    const record = state.missingSpans[button.dataset.missingId];
    if (button.dataset.missingAction === "edit" && record) openMissing(record);
    if (button.dataset.missingAction === "delete") deleteMissingSpan(button.dataset.missingId);
  });
  elements.siblingSpanList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sibling-span-id]");
    if (!button) return;
    const target = state.items.findIndex((candidate) => candidate.span_id === button.dataset.siblingSpanId);
    if (target < 0) return;
    state.currentIndex = target;
    if (!state.filteredIndices.includes(target)) setFilter("all"); else render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  elements.showAllButton.addEventListener("click", () => setFilter("all"));
  elements.annotatorInput.addEventListener("change", () => localStorage.setItem("materialAuditAnnotator", annotatorId()));
  elements.jumpInput.addEventListener("change", () => {
    const requested = Number(elements.jumpInput.value) - 1;
    if (Number.isInteger(requested) && requested >= 0 && requested < state.items.length) {
      state.currentIndex = requested;
      if (!state.filteredIndices.includes(requested)) setFilter("all"); else render();
    } else render();
  });
  elements.filterTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (button) setFilter(button.dataset.filter);
  });
  elements.editAccepted.addEventListener("change", toggleAcceptedFields);
  elements.closeDialog.addEventListener("click", () => elements.editDialog.close());
  elements.cancelEdit.addEventListener("click", () => elements.editDialog.close());
  elements.editForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const accepted = elements.editAccepted.value === "true";
    elements.editDialog.close();
    saveAnnotation({ action: "edit", human_accepted: accepted, human_claim: accepted ? elements.editClaim.value : "", human_scope: accepted ? elements.editScope.value : "", human_property_status: accepted ? elements.editPropertyStatus.value : "", human_visual_observability: accepted ? elements.editObservability.value : "", comment: elements.editComment.value }, { forceAdvance: state.editForceAdvance });
    state.editForceAdvance = false;
  });
  elements.closeMissingDialog.addEventListener("click", () => elements.missingDialog.close());
  elements.cancelMissing.addEventListener("click", () => elements.missingDialog.close());
  elements.useSelectedText.addEventListener("click", () => {
    if (state.selectedReviewId === currentItem().review_id && state.selectedReviewText && currentItem().review.includes(state.selectedReviewText)) {
      elements.missingQuote.value = state.selectedReviewText;
      showToast("선택한 원문을 exact quote에 넣었습니다.");
    } else showToast("먼저 Full Review에서 문장을 드래그해 선택해 주세요.", true);
  });
  elements.missingForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveMissingSpan();
  });
  elements.imageButton.addEventListener("click", () => { elements.zoomedImage.src = elements.productImage.src; elements.imageDialog.showModal(); });
  elements.closeImageDialog.addEventListener("click", () => elements.imageDialog.close());
  elements.imageDialog.addEventListener("click", (event) => { if (event.target === elements.imageDialog) elements.imageDialog.close(); });
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if (typing || elements.editDialog.open || elements.missingDialog.open || elements.imageDialog.open) return;
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) { event.preventDefault(); navigate(-1); }
    if (["ArrowRight", "ArrowDown"].includes(event.key)) { event.preventDefault(); markGoodAndNext(); }
    if (event.key.toLowerCase() === "g") markGood();
    if (event.key.toLowerCase() === "b") markBad();
    if (event.key.toLowerCase() === "e") openEdit();
  });
}

function setFilter(filter) {
  state.filter = filter;
  document.querySelectorAll(".filter-tab").forEach((button) => button.classList.toggle("active", button.dataset.filter === filter));
  updateFilteredIndices();
  state.currentIndex = nearestFilteredIndex() ?? state.currentIndex;
  render();
}

async function init() {
  ["datasetBadge", "progressText", "progressPercent", "progressBar", "annotatorInput", "filterTabs", "allCount", "unreviewedCount", "goodCount", "badCount", "editCount", "newV2Count", "jumpInput", "itemTotal", "emptyState", "auditCard", "showAllButton", "productAsin", "productTitle", "imageQuality", "imageButton", "productImage", "positionLabel", "quoteText", "reviewText", "siblingSummary", "siblingSpanList", "qwenDecision", "qwenClaim", "qwenMetadata", "qwenReason", "reviewStatus", "savedSummary", "previousButton", "nextButton", "resetButton", "badButton", "editButton", "goodButton", "autoAdvance", "saveMessage", "editDialog", "editForm", "closeDialog", "cancelEdit", "editAccepted", "editClaim", "editScope", "editPropertyStatus", "editObservability", "editComment", "addMissingButton", "missingSpanList", "recallCheckStatus", "recallCheckDetail", "toggleRecallCheck", "missingDialog", "missingForm", "missingDialogTitle", "closeMissingDialog", "cancelMissing", "useSelectedText", "missingQuote", "missingClaim", "missingScope", "missingPropertyStatus", "missingIntensity", "missingSentiment", "missingEvidence", "missingObservability", "missingComment", "imageDialog", "closeImageDialog", "zoomedImage", "toast"].forEach((id) => { elements[id] = $(id); });
  setOptions(elements.editScope, scopes);
  setOptions(elements.editPropertyStatus, propertyStatuses);
  setOptions(elements.editObservability, observabilities);
  setOptions(elements.missingScope, scopes);
  setOptions(elements.missingPropertyStatus, propertyStatuses);
  setOptions(elements.missingIntensity, intensities);
  setOptions(elements.missingSentiment, sentiments);
  setOptions(elements.missingEvidence, evidenceBases);
  setOptions(elements.missingObservability, observabilities);
  elements.annotatorInput.value = localStorage.getItem("materialAuditAnnotator") || "";
  bindEvents();
  try {
    const response = await fetch("/api/items");
    if (!response.ok) throw new Error("검수 데이터를 불러오지 못했습니다.");
    const payload = await response.json();
    state.items = payload.items;
    const datasetVersion = payload.dataset_version || "semantic_audit_v1";
    elements.datasetBadge.textContent = datasetVersion.includes("v2") ? "RECALL V2" : "V1";
    state.annotations = payload.annotations;
    state.missingSpans = payload.missing_spans || {};
    state.reviewChecks = payload.review_checks || {};
    updateFilteredIndices();
    render();
  } catch (error) { showToast(error.message, true); }
}

document.addEventListener("DOMContentLoaded", init);
