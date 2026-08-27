// 話者管理パネル(要件定義書 第18〜20章: 名前割当・統合)。
const Speakers = {
  _listEl: null,
  _speakers: [],

  init() {
    this._listEl = document.getElementById("speakers-list");
  },

  reset() {
    this._speakers = [];
    this._listEl.innerHTML = "";
  },

  async refresh() {
    const meetingId = App.state.meetingId;
    if (!meetingId) return;
    this._speakers = await Api.getSpeakers(meetingId);
    const draft = this._captureDraft();
    this._render(draft);
    Transcript.updateSpeakerLabels(this._speakers);
  },

  _activeSpeakers() {
    const spokenIds = Transcript.spokenSpeakerIds();
    return this._speakers.filter(
      (s) => s.merged_into_id == null && spokenIds.has(Number(s.id))
    );
  },

  _participantNames() {
    const names = new Set(Participants.names());
    this._speakers.forEach((s) => {
      const label = s.display_label || "";
      if (label && !/^speaker_\d+$/i.test(label)) names.add(label);
    });
    return Array.from(names);
  },

  _captureDraft() {
    const drafts = new Map();
    let focus = null;
    if (!this._listEl) return { drafts, focus };
    const active = document.activeElement;
    this._listEl.querySelectorAll(".speaker-row").forEach((row) => {
      const id = Number(row.dataset.speakerId);
      if (!Number.isFinite(id)) return;
      const nameInput = row.querySelector('input[data-role="name"]');
      const pickSelect = row.querySelector('select[data-role="pick"]');
      const mergeSelect = row.querySelector('select[data-role="merge"]');
      drafts.set(id, {
        name: nameInput ? nameInput.value : "",
        pick: pickSelect ? pickSelect.value : "",
        merge: mergeSelect ? mergeSelect.value : "",
      });
      if (active && row.contains(active)) {
        focus = {
          speakerId: id,
          field: active.dataset.role || "name",
          start: typeof active.selectionStart === "number" ? active.selectionStart : null,
          end: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
        };
      }
    });
    return { drafts, focus };
  },

  async _assign(speaker, nameInput) {
    const name = nameInput.value.trim();
    if (!name) return;
    await Api.assignSpeaker(App.state.meetingId, speaker.id, name);
    await Participants.refresh();
    await this.refresh();
  },

  _render(draft = { drafts: new Map(), focus: null }) {
    const active = this._activeSpeakers();
    const participantNames = this._participantNames();
    this._listEl.innerHTML = "";
    active.forEach((speaker) => {
      const row = document.createElement("div");
      row.className = "speaker-row";
      row.dataset.speakerId = String(speaker.id);
      const colorClass = speakerColorClass(speaker.id);
      if (colorClass) row.classList.add(colorClass);

      const label = document.createElement("span");
      label.className = "speaker-label";
      label.textContent = speaker.display_label || speaker.label;
      row.appendChild(label);

      const saved = draft.drafts.get(Number(speaker.id)) || {};
      const pickSelect = document.createElement("select");
      pickSelect.dataset.role = "pick";
      const pickDefault = document.createElement("option");
      pickDefault.value = "";
      pickDefault.textContent = "一覧から選択";
      pickSelect.appendChild(pickDefault);
      participantNames.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        pickSelect.appendChild(opt);
      });
      if (saved.pick && [...pickSelect.options].some((opt) => opt.value === saved.pick)) {
        pickSelect.value = saved.pick;
      }
      row.appendChild(pickSelect);

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.dataset.role = "name";
      nameInput.placeholder = "または名前を入力";
      if (saved.name) nameInput.value = saved.name;
      nameInput.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        this._assign(speaker, nameInput);
      });
      row.appendChild(nameInput);

      pickSelect.addEventListener("change", () => {
        if (!pickSelect.value) return;
        nameInput.value = pickSelect.value;
        this._assign(speaker, nameInput);
      });

      const assignBtn = document.createElement("button");
      assignBtn.className = "btn btn-small";
      assignBtn.textContent = "割当";
      assignBtn.addEventListener("click", () => this._assign(speaker, nameInput));
      row.appendChild(assignBtn);

      const mergeSelect = document.createElement("select");
      mergeSelect.dataset.role = "merge";
      const defaultOpt = document.createElement("option");
      defaultOpt.value = "";
      defaultOpt.textContent = "統合先を選択";
      mergeSelect.appendChild(defaultOpt);
      active
        .filter((s) => s.id !== speaker.id)
        .forEach((s) => {
          const opt = document.createElement("option");
          opt.value = s.id;
          opt.textContent = s.display_label || s.label;
          mergeSelect.appendChild(opt);
        });
      if (saved.merge && [...mergeSelect.options].some((opt) => opt.value === saved.merge)) {
        mergeSelect.value = saved.merge;
      }
      row.appendChild(mergeSelect);

      const mergeBtn = document.createElement("button");
      mergeBtn.className = "btn btn-small";
      mergeBtn.textContent = "統合";
      mergeBtn.addEventListener("click", async () => {
        if (!mergeSelect.value) return;
        await Api.mergeSpeaker(App.state.meetingId, speaker.id, mergeSelect.value);
        await this.refresh();
      });
      row.appendChild(mergeBtn);

      this._listEl.appendChild(row);
    });

    this._restoreFocus(draft.focus);
  },

  _restoreFocus(focus) {
    if (!focus) return;
    const row = this._listEl.querySelector(`.speaker-row[data-speaker-id="${focus.speakerId}"]`);
    if (!row) return;
    const el = row.querySelector(`[data-role="${focus.field}"]`);
    if (!el) return;
    el.focus();
    if (focus.field === "name" && typeof el.setSelectionRange === "function") {
      const start = focus.start == null ? el.value.length : focus.start;
      const end = focus.end == null ? start : focus.end;
      try {
        el.setSelectionRange(start, end);
      } catch (err) {
        // フォーカス復元に失敗しても入力自体は残す
      }
    }
  },
};
