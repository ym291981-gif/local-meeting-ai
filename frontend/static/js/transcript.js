// 文字起こし(全文記録)パネルの表示・編集を担当する。
const SPEAKER_COLOR_COUNT = 8;
const SCROLL_BOTTOM_THRESHOLD_PX = 80;

function speakerColorClass(speakerId) {
  if (speakerId == null || speakerId === "") return "";
  const numeric = Number(speakerId);
  if (!Number.isFinite(numeric)) return "";
  const index = ((numeric - 1) % SPEAKER_COLOR_COUNT + SPEAKER_COLOR_COUNT) % SPEAKER_COLOR_COUNT;
  return `speaker-color-${index + 1}`;
}

async function copyToClipboard(text, button) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  if (!button) return;
  const original = button.textContent;
  button.textContent = "コピーしました";
  button.disabled = true;
  setTimeout(() => {
    button.textContent = original;
    button.disabled = false;
  }, 1500);
}

const Transcript = {
  _utterances: new Map(), // id -> utteranceデータ
  _speakerLabels: new Map(), // speaker_id -> 表示名(統合先を解決済み)
  _speakersById: new Map(), // speaker_id -> speaker
  _listEl: null,
  _copyBtn: null,
  _jumpBtn: null,
  _wrapEl: null,
  _stickToBottom: true,
  _editingId: null,

  init() {
    this._listEl = document.getElementById("transcript-list");
    this._wrapEl = document.getElementById("transcript-list-wrap");
    this._copyBtn = document.getElementById("copy-transcript-btn");
    this._jumpBtn = document.getElementById("jump-latest-btn");
    this._copyBtn.addEventListener("click", () => {
      copyToClipboard(this.toPlainText(), this._copyBtn);
    });
    if (this._jumpBtn) {
      this._jumpBtn.addEventListener("click", () => this.jumpToLatest());
    }
    this._listEl.addEventListener("scroll", () => this._onScroll());
    this._updateJumpButton();
  },

  reset() {
    this._utterances.clear();
    this._speakerLabels.clear();
    this._speakersById.clear();
    this._editingId = null;
    this._stickToBottom = true;
    this._listEl.innerHTML = "";
    this._updateCopyButton();
    this._updateJumpButton();
  },

  formatTime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
    const s = String(totalSec % 60).padStart(2, "0");
    return `${m}:${s}`;
  },

  spokenSpeakerIds() {
    const ids = new Set();
    this._utterances.forEach((u) => {
      const speakerId = this._canonicalSpeakerId(u.effective_speaker_id ?? u.speaker_id);
      if (speakerId != null) ids.add(Number(speakerId));
    });
    return ids;
  },

  setAll(utterances) {
    this.reset();
    utterances.forEach((u) => {
      this._utterances.set(u.id, { ...(this._utterances.get(u.id) || {}), ...u });
    });
    this._renderAll();
  },

  upsert(u, render = true) {
    const isNew = !this._utterances.has(u.id);
    const previous = this._utterances.get(u.id) || {};
    const merged = { ...previous, ...u };
    this._utterances.set(u.id, merged);
    if (!render) return;
    if (isNew) {
      this._insertRow(merged);
    } else {
      this._patchRow(merged);
    }
    this._maybeScrollToBottom();
    this._updateCopyButton();
  },

  updateSpeakerLabels(speakers) {
    this._speakersById = new Map(speakers.map((s) => [Number(s.id), s]));
    this._speakerLabels.clear();
    speakers.forEach((s) => {
      const resolved = this._resolveSpeaker(s.id) || s;
      this._speakerLabels.set(Number(s.id), resolved.display_label || resolved.label);
    });
    // 編集中の行以外はラベルだけ更新し、スクロール位置を維持する
    const savedScroll = this._listEl.scrollTop;
    this._utterances.forEach((u) => {
      if (this._editingId != null && Number(this._editingId) === Number(u.id)) return;
      this._patchRow(u);
    });
    if (!this._stickToBottom) {
      this._listEl.scrollTop = savedScroll;
    } else {
      this._maybeScrollToBottom();
    }
  },

  jumpToLatest() {
    this._stickToBottom = true;
    this._listEl.scrollTop = this._listEl.scrollHeight;
    this._updateJumpButton();
  },

  _onScroll() {
    const el = this._listEl;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    this._stickToBottom = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD_PX;
    this._updateJumpButton();
  },

  _maybeScrollToBottom() {
    if (!this._stickToBottom) {
      this._updateJumpButton();
      return;
    }
    this._listEl.scrollTop = this._listEl.scrollHeight;
    this._updateJumpButton();
  },

  _updateJumpButton() {
    if (!this._jumpBtn) return;
    this._jumpBtn.hidden = this._stickToBottom || this._utterances.size === 0;
  },

  _resolveSpeaker(speakerId) {
    if (speakerId == null || speakerId === "") return null;
    let current = this._speakersById.get(Number(speakerId));
    const seen = new Set();
    while (current && current.merged_into_id != null && !seen.has(Number(current.id))) {
      seen.add(Number(current.id));
      current = this._speakersById.get(Number(current.merged_into_id));
    }
    return current || null;
  },

  _canonicalSpeakerId(speakerId) {
    if (speakerId == null || speakerId === "") return null;
    const resolved = this._resolveSpeaker(speakerId);
    return resolved ? Number(resolved.id) : Number(speakerId);
  },

  _speakerIdFor(u) {
    return this._canonicalSpeakerId(u.effective_speaker_id ?? u.speaker_id);
  },

  _speakerNameFor(u) {
    const rawId = u.effective_speaker_id ?? u.speaker_id;
    if (rawId != null && this._speakerLabels.has(Number(rawId))) {
      return this._speakerLabels.get(Number(rawId));
    }
    const canonicalId = this._speakerIdFor(u);
    if (canonicalId != null && this._speakerLabels.has(Number(canonicalId))) {
      return this._speakerLabels.get(Number(canonicalId));
    }
    return u.speaker_label || "話者未確定";
  },

  _textFor(u) {
    return u.effective_text ?? u.corrected_text ?? u.raw_text ?? u.text ?? "";
  },

  toPlainText() {
    const sorted = Array.from(this._utterances.values()).sort((a, b) => a.start_ms - b.start_ms);
    return sorted
      .map((u) => {
        const text = this._textFor(u).trim();
        if (!text) return "";
        return `[${this.formatTime(u.start_ms)}] ${this._speakerNameFor(u)}\n${text}`;
      })
      .filter(Boolean)
      .join("\n\n");
  },

  _updateCopyButton() {
    if (!this._copyBtn) return;
    this._copyBtn.disabled = this._utterances.size === 0;
  },

  _sortedUtterances() {
    return Array.from(this._utterances.values()).sort((a, b) => a.start_ms - b.start_ms);
  },

  _renderAll() {
    const savedScroll = this._listEl.scrollTop;
    const editingId = this._editingId;
    this._listEl.innerHTML = "";
    this._sortedUtterances().forEach((u) => {
      this._listEl.appendChild(this._renderRow(u));
    });
    if (this._stickToBottom) {
      this._listEl.scrollTop = this._listEl.scrollHeight;
    } else {
      this._listEl.scrollTop = savedScroll;
    }
    this._updateCopyButton();
    this._updateJumpButton();
    // 編集中だった行は再オープンしない（フル再描画時は編集状態を閉じる）
    if (editingId != null) this._editingId = null;
  },

  _findRow(id) {
    return this._listEl.querySelector(`.utterance-row[data-id="${id}"]`);
  },

  _insertRow(u) {
    const row = this._renderRow(u);
    const sorted = this._sortedUtterances();
    const index = sorted.findIndex((item) => Number(item.id) === Number(u.id));
    if (index < 0 || index === sorted.length - 1) {
      this._listEl.appendChild(row);
      return;
    }
    const next = sorted[index + 1];
    const nextRow = this._findRow(next.id);
    if (nextRow) {
      this._listEl.insertBefore(row, nextRow);
    } else {
      this._listEl.appendChild(row);
    }
  },

  _patchRow(u) {
    const existing = this._findRow(u.id);
    if (!existing) {
      this._insertRow(u);
      return;
    }
    if (existing.querySelector("textarea")) return; // 編集中は触らない

    const replacement = this._renderRow(u);
    existing.replaceWith(replacement);
  },

  _applySpeakerColor(row, u) {
    for (let i = 1; i <= SPEAKER_COLOR_COUNT; i++) {
      row.classList.remove(`speaker-color-${i}`);
    }
    const colorClass = speakerColorClass(this._speakerIdFor(u));
    if (colorClass) row.classList.add(colorClass);
  },

  _renderRow(u) {
    const row = document.createElement("div");
    row.className = "utterance-row";
    row.dataset.id = u.id;
    this._applySpeakerColor(row, u);

    const meta = document.createElement("div");
    meta.className = "utterance-meta";

    const timeEl = document.createElement("span");
    timeEl.textContent = this.formatTime(u.start_ms);
    meta.appendChild(timeEl);

    const speakerEl = document.createElement("span");
    speakerEl.className = "utterance-speaker";
    speakerEl.textContent = this._speakerNameFor(u);
    meta.appendChild(speakerEl);
    row.appendChild(meta);

    const text = document.createElement("div");
    const raw = u.raw_text ?? u.text;
    const isCorrected = u.corrected_text != null && raw != null && u.corrected_text !== raw;
    text.className = "utterance-text" + (isCorrected ? " corrected" : "");
    text.textContent = this._textFor(u);
    row.appendChild(text);

    row.addEventListener("click", () => this._openEditor(row, u));
    return row;
  },

  _speakerOptions() {
    const spoken = this.spokenSpeakerIds();
    const options = [];
    this._speakersById.forEach((s) => {
      if (s.merged_into_id != null) return;
      if (!spoken.has(Number(s.id))) return;
      options.push({
        id: Number(s.id),
        label: s.display_label || s.label || `話者${s.id}`,
      });
    });
    options.sort((a, b) => a.id - b.id);
    return options;
  },

  _openEditor(row, u) {
    if (row.querySelector(".utterance-editor")) return;
    this._editingId = u.id;

    const editor = document.createElement("div");
    editor.className = "utterance-editor";
    editor.addEventListener("click", (ev) => ev.stopPropagation());

    const speakerLabel = document.createElement("label");
    speakerLabel.className = "utterance-editor-label";
    speakerLabel.textContent = "話者";

    const select = document.createElement("select");
    select.className = "utterance-speaker-select";
    const currentId = this._speakerIdFor(u);
    const options = this._speakerOptions();
    if (options.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "話者未確定";
      select.appendChild(opt);
    } else {
      options.forEach((o) => {
        const opt = document.createElement("option");
        opt.value = String(o.id);
        opt.textContent = o.label;
        if (currentId != null && Number(o.id) === Number(currentId)) opt.selected = true;
        select.appendChild(opt);
      });
    }

    const textarea = document.createElement("textarea");
    textarea.value = this._textFor(u);
    textarea.rows = 3;

    const actions = document.createElement("div");
    actions.className = "utterance-editor-actions";

    const saveBtn = document.createElement("button");
    saveBtn.className = "btn btn-small";
    saveBtn.textContent = "保存";
    saveBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const meetingId = App.state.meetingId;
      if (!meetingId) return;
      const payload = { corrected_text: textarea.value };
      if (select.value !== "") {
        payload.corrected_speaker_id = Number(select.value);
      }
      try {
        const updated = await Api.correctUtterance(meetingId, u.id, payload);
        this._editingId = null;
        this.upsert(updated);
      } catch (err) {
        console.error(err);
        alert(`保存に失敗しました: ${err.message}`);
      }
    });

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn btn-small";
    cancelBtn.textContent = "キャンセル";
    cancelBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._editingId = null;
      this._patchRow(this._utterances.get(u.id) || u);
    });

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);

    editor.appendChild(speakerLabel);
    editor.appendChild(select);
    editor.appendChild(textarea);
    editor.appendChild(actions);
    row.appendChild(editor);
  },
};
