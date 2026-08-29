// アプリ全体の状態管理・画面初期化(会議の開始/終了、WebSocket接続の統括)。
const App = {
  state: {
    meetingId: null,
    isRunning: false,
    ws: null,
    speakerRefreshTimer: null,
    hasConnectedOnce: false,
  },

  init() {
    Transcript.init();
    Minutes.init();
    Speakers.init();
    Participants.init();

    document.getElementById("start-meeting-btn").addEventListener("click", () => this.startMeeting());
    document.getElementById("stop-meeting-btn").addEventListener("click", () => this.stopMeeting());
  },

  _setStatus(text) {
    document.getElementById("meeting-status").textContent = text;
  },

  _setConnectionBanner(text) {
    const el = document.getElementById("connection-banner");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = text;
  },

  _wsHandlers(meetingId) {
    return {
      onUtterance: (u) => {
        Transcript.upsert(u.speaker_label ? u : { ...u, speaker_label: null });
        this._scheduleSpeakerRefresh();
      },
      onMinutes: (m) => Minutes.render(m),
      onMeetingEnded: () => this._setStatus(`会議は終了しました(ID: ${meetingId})`),
      onConnected: () => {
        const wasReconnect = this.state.hasConnectedOnce;
        this.state.hasConnectedOnce = true;
        this._setConnectionBanner("");
        if (wasReconnect) {
          this._resyncAfterReconnect(meetingId);
        }
      },
      onDisconnected: () => {
        if (!this.state.isRunning) return;
        this._setConnectionBanner("接続が切れました。再接続中…");
      },
    };
  },

  async _resyncAfterReconnect(meetingId) {
    if (!this.state.isRunning || this.state.meetingId !== meetingId) return;
    try {
      const [transcript, minutes] = await Promise.all([
        Api.getTranscript(meetingId),
        Api.getLatestMinutes(meetingId),
      ]);
      Transcript.setAll(transcript);
      if (minutes) Minutes.render(minutes);
      await Speakers.refresh();
      this._setConnectionBanner("");
      this._setStatus(`会議進行中(ID: ${meetingId}) — 再同期済み`);
    } catch (err) {
      console.error(err);
      this._setConnectionBanner(`再同期に失敗しました: ${err.message}`);
    }
  },

  async startMeeting() {
    const title = document.getElementById("meeting-title-input").value.trim();
    const rawCount = document.getElementById("speaker-count-input").value;
    const minSpeakers = rawCount === "" ? null : Number(rawCount);
    const summaryMode =
      document.getElementById("summary-mode-select")?.value || "auto";
    this._setStatus("会議を開始しています...");
    try {
      const meeting = await Api.createMeeting(title, minSpeakers, summaryMode);
      this.state.meetingId = meeting.id;
      await Participants.commitPending(meeting.id);
      this.state.isRunning = true;
      this.state.hasConnectedOnce = false;

      Transcript.reset();
      Minutes.reset();
      Speakers.reset();
      this._setConnectionBanner("");

      document.getElementById("start-meeting-btn").disabled = true;
      document.getElementById("stop-meeting-btn").disabled = false;
      this._setStatus(`会議進行中(ID: ${meeting.id})`);

      if (this.state.ws) {
        this.state.ws.close();
        this.state.ws = null;
      }
      this.state.ws = Api.connectWebSocket(meeting.id, this._wsHandlers(meeting.id));

      await Participants.refresh();
      await Speakers.refresh();
    } catch (err) {
      console.error(err);
      this._setStatus(`エラー: ${err.message}`);
    }
  },

  _scheduleSpeakerRefresh() {
    // 発言ごとに毎回話者一覧を取りに行うと負荷が高いため、少し間隔を空けてまとめて更新する
    if (this.state.speakerRefreshTimer) return;
    this.state.speakerRefreshTimer = setTimeout(async () => {
      this.state.speakerRefreshTimer = null;
      await Speakers.refresh();
    }, 1500);
  },

  async stopMeeting() {
    if (!this.state.meetingId) return;
    this._setStatus("会議を終了処理中です(最終議事録を生成しています)...");
    document.getElementById("stop-meeting-btn").disabled = true;
    this.state.isRunning = false;
    if (this.state.ws) {
      this.state.ws.close();
      this.state.ws = null;
    }
    this._setConnectionBanner("");
    try {
      await Api.stopMeeting(this.state.meetingId);
      const [transcript, minutes] = await Promise.all([
        Api.getTranscript(this.state.meetingId),
        Api.getLatestMinutes(this.state.meetingId),
      ]);
      Transcript.setAll(transcript);
      if (minutes) Minutes.render(minutes);
      await Speakers.refresh();

      Participants.prepareNextMeeting();

      this._setStatus(`会議は終了しました(ID: ${this.state.meetingId})`);
      document.getElementById("start-meeting-btn").disabled = false;
    } catch (err) {
      console.error(err);
      this._setStatus(`エラー: ${err.message}`);
      document.getElementById("stop-meeting-btn").disabled = false;
      this.state.isRunning = true;
    }
  },
};

document.addEventListener("DOMContentLoaded", () => App.init());
