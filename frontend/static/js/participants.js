// 参加者一覧パネル(要件定義書 第22章)。
const Participants = {
  _listEl: null,
  _nameInput: null,
  _addBtn: null,

  init() {
    this._listEl = document.getElementById("participants-list");
    this._nameInput = document.getElementById("participant-name-input");
    this._addBtn = document.getElementById("add-participant-btn");
    this._addBtn.addEventListener("click", () => this._add());
  },

  reset() {
    this._listEl.innerHTML = "";
  },

  async refresh() {
    const meetingId = App.state.meetingId;
    if (!meetingId) return;
    const participants = await Api.getParticipants(meetingId);
    this._render(participants);
  },

  async _add() {
    const meetingId = App.state.meetingId;
    const name = this._nameInput.value.trim();
    if (!meetingId || !name) return;
    await Api.addParticipant(meetingId, name);
    this._nameInput.value = "";
    await this.refresh();
  },

  _render(participants) {
    this._listEl.innerHTML = "";
    participants.forEach((p) => {
      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.textContent = p.name;
      li.appendChild(nameSpan);

      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-small";
      delBtn.textContent = "削除";
      delBtn.addEventListener("click", async () => {
        await Api.deleteParticipant(App.state.meetingId, p.id);
        await this.refresh();
      });
      li.appendChild(delBtn);

      this._listEl.appendChild(li);
    });
  },
};
