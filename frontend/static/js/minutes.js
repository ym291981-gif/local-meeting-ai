// 議事録パネルの表示・修正を担当する(要件定義書 第23〜26章)。
const Minutes = {
  _current: null,
  _viewEl: null,
  _formEl: null,
  _editBtn: null,
  _copyBtn: null,

  init() {
    this._viewEl = document.getElementById("minutes-view");
    this._formEl = document.getElementById("minutes-edit-form");
    this._editBtn = document.getElementById("edit-minutes-btn");
    this._copyBtn = document.getElementById("copy-minutes-btn");
    this._editBtn.addEventListener("click", () => this._toggleEdit());
    this._copyBtn.addEventListener("click", () => {
      copyToClipboard(this.toPlainText(), this._copyBtn);
    });
  },

  reset() {
    this._current = null;
    this._viewEl.innerHTML = '<p class="empty-hint">まだ議事録は生成されていません。</p>';
    this._formEl.hidden = true;
    this._formEl.innerHTML = "";
    this._editBtn.disabled = true;
    this._copyBtn.disabled = true;
  },

  render(data) {
    this._current = data;
    this._editBtn.disabled = false;
    this._formEl.hidden = true;

    const section = (title, items, renderItem) => {
      if (!items || items.length === 0) return "";
      const lis = items.map((item) => `<li>${renderItem(item)}</li>`).join("");
      return `<section><h3>${title}</h3><ul>${lis}</ul></section>`;
    };

    const html = [
      data.is_final ? '<p class="empty-hint">(会議終了 最終議事録)</p>' : "",
      section("議題", data.topics, (t) => this._escape(t.title)),
      section("決定事項", data.decisions, (d) => this._escape(d.text)),
      section(
        "ToDo",
        data.todos,
        (t) =>
          `<div class="todo-item"><span>${this._escape(t.task)}</span>` +
          (t.owner ? `<span class="todo-owner">担当: ${this._escape(t.owner)}</span>` : "") +
          (t.deadline ? `<span class="todo-deadline">期限: ${this._escape(t.deadline)}</span>` : "") +
          `</div>`
      ),
      section("保留事項", data.pending_items, (p) => this._escape(p.text)),
      section("確認事項", data.confirmations, (c) => this._escape(c.text)),
      section("前回からの変更事項", data.changes_from_previous, (c) => this._escape(c.text)),
    ]
      .filter(Boolean)
      .join("");

    this._viewEl.innerHTML =
      html || '<p class="empty-hint">議事録の内容はまだありません。</p>';
    this._copyBtn.disabled = !this.toPlainText();
  },

  toPlainText() {
    const data = this._current;
    if (!data) return "";
    const lines = [];
    const addSection = (title, items, mapper) => {
      if (!items || items.length === 0) return;
      lines.push(title);
      items.forEach((item) => {
        const text = mapper(item);
        if (text) lines.push(`- ${text}`);
      });
      lines.push("");
    };
    addSection("議題", data.topics, (t) => t.title);
    addSection("決定事項", data.decisions, (d) => d.text);
    addSection("ToDo", data.todos, (t) => {
      const bits = [t.task];
      if (t.owner) bits.push(`担当: ${t.owner}`);
      if (t.deadline) bits.push(`期限: ${t.deadline}`);
      return bits.join(" / ");
    });
    addSection("保留事項", data.pending_items, (p) => p.text);
    addSection("確認事項", data.confirmations, (c) => c.text);
    addSection("前回からの変更事項", data.changes_from_previous, (c) => c.text);
    return lines.join("\n").trim();
  },

  _escape(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  },

  _toggleEdit() {
    if (!this._formEl.hidden) {
      this._formEl.hidden = true;
      return;
    }
    this._buildEditForm();
    this._formEl.hidden = false;
  },

  _linesToTextArea(items, mapper) {
    return (items || []).map(mapper).join("\n");
  },

  _buildEditForm() {
    const data = this._current || {};
    this._formEl.innerHTML = `
      <label>議題(1行1件)</label>
      <textarea id="edit-topics">${this._linesToTextArea(data.topics, (t) => t.title)}</textarea>
      <label>決定事項(1行1件)</label>
      <textarea id="edit-decisions">${this._linesToTextArea(data.decisions, (d) => d.text)}</textarea>
      <label>ToDo(1行1件、「作業内容 | 担当者 | 期限」の形式)</label>
      <textarea id="edit-todos">${this._linesToTextArea(
        data.todos,
        (t) => `${t.task} | ${t.owner || ""} | ${t.deadline || ""}`
      )}</textarea>
      <label>保留事項(1行1件)</label>
      <textarea id="edit-pending">${this._linesToTextArea(data.pending_items, (p) => p.text)}</textarea>
      <label>確認事項(1行1件)</label>
      <textarea id="edit-confirmations">${this._linesToTextArea(
        data.confirmations,
        (c) => c.text
      )}</textarea>
      <label>前回からの変更事項(1行1件)</label>
      <textarea id="edit-changes">${this._linesToTextArea(
        data.changes_from_previous,
        (c) => c.text
      )}</textarea>
      <button id="save-minutes-btn" class="btn btn-primary btn-small">保存</button>
    `;
    this._formEl.querySelector("#save-minutes-btn").addEventListener("click", () => this._save());
  },

  _parseLines(text) {
    return text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  },

  async _save() {
    const meetingId = App.state.meetingId;
    const payload = {
      topics: this._parseLines(document.getElementById("edit-topics").value).map((title) => ({
        title,
      })),
      decisions: this._parseLines(document.getElementById("edit-decisions").value).map((text) => ({
        text,
      })),
      todos: this._parseLines(document.getElementById("edit-todos").value).map((line) => {
        const [task, owner, deadline] = line.split("|").map((s) => (s || "").trim());
        return { task, owner: owner || null, deadline: deadline || null };
      }),
      pending_items: this._parseLines(document.getElementById("edit-pending").value).map((text) => ({
        text,
      })),
      confirmations: this._parseLines(document.getElementById("edit-confirmations").value).map(
        (text) => ({ text })
      ),
      changes_from_previous: this._parseLines(document.getElementById("edit-changes").value).map(
        (text) => ({ text })
      ),
    };
    const updated = await Api.editMinutes(meetingId, payload);
    this.render(updated);
  },
};
