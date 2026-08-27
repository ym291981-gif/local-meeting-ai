// 参加者一覧パネル(要件定義書 第22章)。
// 会議開始前は _pending に名前を置き、開始成功後に API へまとめて登録する。
const Participants = {
  _listEl: null,
  _nameInput: null,
  _addBtn: null,
  _items: [],
  _pending: [],

  init() {
    this._listEl = document.getElementById("participants-list");
    this._nameInput = document.getElementById("participant-name-input");
    this._addBtn = document.getElementById("add-participant-btn");
    this._addBtn.addEventListener("click", () => this._add());
    this._nameInput.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      this._add();
    });
  },

  _isBound() {
    return Boolean(App.state.meetingId && App.state.isRunning);
  },

  names() {
    const names = new Set(this._pending);
    this._items.forEach((p) => {
      if (p.name) names.add(p.name);
    });
    return Array.from(names);
  },

  async refresh() {
    const meetingId = App.state.meetingId;
    if (!meetingId || !this._isBound()) {
      this._syncList();
      return;
    }
    this._items = await Api.getParticipants(meetingId);
    this._syncList();
  },

  async commitPending(meetingId) {
    try {
      const names = this._pending.slice();
      for (const name of names) {
        await Api.addParticipant(meetingId, name);
        this._pending = this._pending.filter((n) => n !== name);
      }
    } finally {
      this._syncList();
    }
  },

  clearPending() {
    this._pending = [];
  },

  prepareNextMeeting() {
    this.clearPending();
    this._syncList();
  },

  async _add() {
    const name = this._nameInput.value.trim();
    if (!name) return;

    if (!this._isBound()) {
      if (this._pending.includes(name)) {
        this._nameInput.value = "";
        return;
      }
      this._pending.push(name);
      this._nameInput.value = "";
      this._syncList();
      return;
    }

    if (this._items.some((p) => p.name === name)) {
      this._nameInput.value = "";
      return;
    }
    await Api.addParticipant(App.state.meetingId, name);
    this._nameInput.value = "";
    await this.refresh();
    await Speakers.refresh();
  },

  _syncList() {
    if (!this._isBound()) {
      this._render(
        this._pending.map((name) => ({ id: null, name })),
        { pending: true }
      );
      return;
    }
    this._render(this._items, { pending: false });
  },

  _render(participants, options = {}) {
    const pending = Boolean(options.pending);
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
        if (pending || p.id == null) {
          this._pending = this._pending.filter((n) => n !== p.name);
          this._syncList();
          return;
        }
        await Api.deleteParticipant(App.state.meetingId, p.id);
        await this.refresh();
        await Speakers.refresh();
      });
      li.appendChild(delBtn);

      this._listEl.appendChild(li);
    });
  },
};
