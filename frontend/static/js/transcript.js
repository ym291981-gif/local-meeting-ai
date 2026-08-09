// 文字起こし(全文記録)パネルの表示・編集を担当する。
const Transcript = {
  _utterances: new Map(), // id -> utteranceデータ
  _speakerLabels: new Map(), // speaker_id -> 表示名
  _listEl: null,

  init() {
    this._listEl = document.getElementById("transcript-list");
  },

  reset() {
    this._utterances.clear();
    this._listEl.innerHTML = "";
  },

  formatTime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
    const s = String(totalSec % 60).padStart(2, "0");
    return `${m}:${s}`;
  },

  setAll(utterances) {
    this.reset();
    utterances.forEach((u) => this.upsert(u, false));
    this._renderAll();
  },

  upsert(u, render = true) {
    this._utterances.set(u.id, u);
    if (render) this._renderAll();
  },

  updateSpeakerLabels(speakers) {
    speakers.forEach((s) => {
      this._speakerLabels.set(s.id, s.display_label || s.label);
    });
    this._renderAll();
  },

  _speakerNameFor(u) {
    const speakerId = u.effective_speaker_id ?? u.speaker_id;
    if (speakerId && this._speakerLabels.has(speakerId)) {
      return this._speakerLabels.get(speakerId);
    }
    return u.speaker_label || "話者未確定";
  },

  _renderAll() {
    const sorted = Array.from(this._utterances.values()).sort((a, b) => a.start_ms - b.start_ms);
    this._listEl.innerHTML = "";
    sorted.forEach((u) => this._listEl.appendChild(this._renderRow(u)));
    this._listEl.scrollTop = this._listEl.scrollHeight;
  },

  _renderRow(u) {
    const row = document.createElement("div");
    row.className = "utterance-row";
    row.dataset.id = u.id;

    const meta = document.createElement("div");
    meta.className = "utterance-meta";
    meta.innerHTML = `<span>${this.formatTime(u.start_ms)}</span><span class="utterance-speaker">${this._speakerNameFor(u)}</span>`;
    row.appendChild(meta);

    const text = document.createElement("div");
    const isCorrected = u.corrected_text != null && u.corrected_text !== u.raw_text;
    text.className = "utterance-text" + (isCorrected ? " corrected" : "");
    text.textContent = u.effective_text ?? u.corrected_text ?? u.raw_text;
    row.appendChild(text);

    row.addEventListener("click", () => this._openEditor(row, u));
    return row;
  },

  _openEditor(row, u) {
    if (row.querySelector("textarea")) return; // 既に編集中

    const textarea = document.createElement("textarea");
    textarea.value = u.effective_text ?? u.raw_text;
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
