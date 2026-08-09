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
    this._render();
    Transcript.updateSpeakerLabels(this._speakers);
  },

  _activeSpeakers() {
    return this._speakers.filter((s) => s.merged_into_id == null);
  },

  _render() {
    const active = this._activeSpeakers();
    this._listEl.innerHTML = "";
    active.forEach((speaker) => {
      const row = document.createElement("div");
      row.className = "speaker-row";

      const label = document.createElement("span");
      label.className = "speaker-label";
      label.textContent = speaker.display_label || speaker.label;
      row.appendChild(label);

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.placeholder = "参加者名を入力";
      row.appendChild(nameInput);

      const assignBtn = document.createElement("button");
      assignBtn.className = "btn btn-small";
      assignBtn.textContent = "割当";
      assignBtn.addEventListener("click", async () => {
        if (!nameInput.value.trim()) return;
        await Api.assignSpeaker(App.state.meetingId, speaker.id, nameInput.value.trim());
        await this.refresh();
      });
      row.appendChild(assignBtn);

      const mergeSelect = document.createElement("select");
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
  },
};
