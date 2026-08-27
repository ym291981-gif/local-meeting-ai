// 文字起こし(全文記録)パネルの表示・編集を担当する。
const SPEAKER_COLOR_COUNT = 8;

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

  init() {
    this._listEl = document.getElementById("transcript-list");
    this._copyBtn = document.getElementById("copy-transcript-btn");
    this._copyBtn.addEventListener("click", () => {
      copyToClipboard(this.toPlainText(), this._copyBtn);
    });
  },

  reset() {
    this._utterances.clear();
    this._speakerLabels.clear();
    this._speakersById.clear();
    this._listEl.innerHTML = "";
    this._updateCopyButton();
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
    utterances.forEach((u) => this.upsert(u, false));
    this._renderAll();
  },

  upsert(u, render = true) {
    const previous = this._utterances.get(u.id) || {};
    this._utterances.set(u.id, { ...previous, ...u });
    if (render) this._renderAll();
  },

  updateSpeakerLabels(speakers) {
    this._speakersById = new Map(speakers.map((s) => [Number(s.id), s]));
    this._speakerLabels.clear();
    speakers.forEach((s) => {
      const resolved = this._resolveSpeaker(s.id) || s;
      this._speakerLabels.set(Number(s.id), resolved.display_label || resolved.label);
    });
    this._renderAll();
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

  _renderAll() {
    const sorted = Array.from(this._utterances.values()).sort((a, b) => a.start_ms - b.start_ms);
    this._listEl.innerHTML = "";
    sorted.forEach((u) => this._listEl.appendChild(this._renderRow(u)));
    this._listEl.scrollTop = this._listEl.scrollHeight;
    this._updateCopyButton();
  },

  _renderRow(u) {
    const row = document.createElement("div");
    row.className = "utterance-row";
    row.dataset.id = u.id;
    const colorClass = speakerColorClass(this._speakerIdFor(u));
    if (colorClass) row.classList.add(colorClass);

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

  _openEditor(row, u) {
    if (row.querySelector("textarea")) return; // 既に編集中

    const textarea = document.createElement("textarea");
    textarea.value = this._textFor(u);
    textarea.style.width = "100%";
    textarea.style.minHeight = "60px";

    const saveBtn = document.createElement("button");
    saveBtn.className = "btn btn-small";
    saveBtn.textContent = "保存";
    saveBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const meetingId = App.state.meetingId;
      const updated = await Api.correctUtterance(meetingId, u.id, {
        corrected_text: textarea.value,
      });
      this.upsert(updated);
    });

    row.appendChild(textarea);
    row.appendChild(saveBtn);
  },
};
