// まとめパネルの表示・修正を担当する(柔軟セクション形式)。
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
    this._viewEl.innerHTML = '<p class="empty-hint">まだまとめは生成されていません。</p>';
    this._formEl.hidden = true;
    this._formEl.innerHTML = "";
    this._editBtn.disabled = true;
    this._copyBtn.disabled = true;
  },

  _sectionsOf(data) {
    if (!data) return [];
    return Array.isArray(data.sections) ? data.sections : [];
  },

  _itemLabel(item) {
    if (!item) return "";
    const bits = [item.text || ""];
    if (item.owner) bits.push(`担当: ${item.owner}`);
    if (item.deadline) bits.push(`期限: ${item.deadline}`);
    return bits.filter(Boolean).join(" / ");
  },

  _renderItemHtml(item) {
    const text = this._escape(item.text || "");
    const extras = [];
    if (item.owner) extras.push(`<span class="todo-owner">担当: ${this._escape(item.owner)}</span>`);
    if (item.deadline) {
      extras.push(`<span class="todo-deadline">期限: ${this._escape(item.deadline)}</span>`);
    }
    if (extras.length === 0) return text;
    return `<div class="todo-item"><span>${text}</span>${extras.join("")}</div>`;
  },

  render(data) {
    this._current = data;
    this._editBtn.disabled = false;
    this._formEl.hidden = true;

    const sections = this._sectionsOf(data);
    const parts = [];
    if (data && data.is_final) {
      parts.push('<p class="empty-hint">(終了 最終まとめ)</p>');
    }
    sections.forEach((section) => {
      const items = Array.isArray(section.items) ? section.items : [];
      if (!section.title || items.length === 0) return;
      const lis = items.map((item) => `<li>${this._renderItemHtml(item)}</li>`).join("");
      parts.push(
        `<section><h3>${this._escape(section.title)}</h3><ul>${lis}</ul></section>`
      );
    });

    this._viewEl.innerHTML =
      parts.join("") || '<p class="empty-hint">まとめの内容はまだありません。</p>';
    this._copyBtn.disabled = !this.toPlainText();
  },

  toPlainText() {
    const sections = this._sectionsOf(this._current);
    const lines = [];
    sections.forEach((section) => {
      const items = Array.isArray(section.items) ? section.items : [];
      if (!section.title || items.length === 0) return;
      lines.push(section.title);
      items.forEach((item) => {
        const text = this._itemLabel(item);
        if (text) lines.push(`- ${text}`);
      });
      lines.push("");
    });
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

  _buildEditForm() {
    const sections = this._sectionsOf(this._current);
    const blocks =
      sections.length > 0
        ? sections
            .map((section, index) => {
              const itemsText = (section.items || [])
                .map((item) => this._itemLabel(item))
                .join("\n");
              return `
          <div class="minutes-section-editor" data-index="${index}">
            <label>見出し</label>
            <input type="text" class="edit-section-title" value="${this._escape(section.title || "")}" />
            <label>箇条書き(1行1件)</label>
            <textarea class="edit-section-items" rows="4">${this._escape(itemsText)}</textarea>
            <button type="button" class="btn btn-small remove-section-btn">この見出しを削除</button>
          </div>`;
            })
            .join("")
        : `
        <div class="minutes-section-editor" data-index="0">
          <label>見出し</label>
          <input type="text" class="edit-section-title" value="" placeholder="例: 要点" />
          <label>箇条書き(1行1件)</label>
          <textarea class="edit-section-items" rows="4"></textarea>
          <button type="button" class="btn btn-small remove-section-btn">この見出しを削除</button>
        </div>`;

    this._formEl.innerHTML = `
      <div id="minutes-sections-editors">${blocks}</div>
      <div class="utterance-editor-actions">
        <button type="button" id="add-section-btn" class="btn btn-small">見出しを追加</button>
        <button type="button" id="save-minutes-btn" class="btn btn-primary btn-small">保存</button>
      </div>
    `;

    this._formEl.querySelector("#add-section-btn").addEventListener("click", () => {
      const container = this._formEl.querySelector("#minutes-sections-editors");
      const div = document.createElement("div");
      div.className = "minutes-section-editor";
      div.innerHTML = `
        <label>見出し</label>
        <input type="text" class="edit-section-title" value="" />
        <label>箇条書き(1行1件)</label>
        <textarea class="edit-section-items" rows="4"></textarea>
        <button type="button" class="btn btn-small remove-section-btn">この見出しを削除</button>
      `;
      container.appendChild(div);
      div.querySelector(".remove-section-btn").addEventListener("click", () => div.remove());
    });

    this._formEl.querySelectorAll(".remove-section-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const block = btn.closest(".minutes-section-editor");
        if (block) block.remove();
      });
    });

    this._formEl.querySelector("#save-minutes-btn").addEventListener("click", () => this._save());
  },

  _parseLines(text) {
    return text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  },

  _collectSectionsFromForm() {
    const blocks = this._formEl.querySelectorAll(".minutes-section-editor");
    const sections = [];
    blocks.forEach((block) => {
      const title = (block.querySelector(".edit-section-title").value || "").trim();
      const lines = this._parseLines(block.querySelector(".edit-section-items").value);
      if (!title && lines.length === 0) return;
      sections.push({
        title: title || "無題",
        items: lines.map((text) => ({ text })),
      });
    });
    return sections;
  },

  async _save() {
    const meetingId = App.state.meetingId;
    const payload = { sections: this._collectSectionsFromForm() };
    const updated = await Api.editMinutes(meetingId, payload);
    this.render(updated);
  },
};
