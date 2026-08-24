// アプリ全体の状態管理・画面初期化(会議の開始/終了、WebSocket接続の統括)。
const App = {
  state: {
    meetingId: null,
    ws: null,
    speakerRefreshTimer: null,
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

  async startMeeting() {
    const title = document.getElementById("meeting-title-input").value.trim();
    const rawCount = document.getElementById("speaker-count-input").value;
    const minSpeakers = rawCount === "" ? null : Number(rawCount);
    this._setStatus("会議を開始しています...");
    try {
      const meeting = await Api.createMeeting(title, minSpeakers);
      this.state.meetingId = meeting.id;

      Transcript.reset();
      Minutes.reset();
      Speakers.reset();
      Participants.reset();

      document.getElementById("start-meeting-btn").disabled = true;
      document.getElementById("stop-meeting-btn").disabled = false;
      this._setStatus(`会議進行中(ID: ${meeting.id})`);

      this.state.ws = Api.connectWebSocket(meeting.id, {
        onUtterance: (u) => {
          Transcript.upsert(u.speaker_label ? u : { ...u, speaker_label: null });
          this._scheduleSpeakerRefresh();
        },
        onMinutes: (m) => Minutes.render(m),
        onMeetingEnded: () => this._setStatus(`会議は終了しました(ID: ${meeting.id})`),
      });

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
    try {
      await Api.stopMeeting(this.state.meetingId);
      const [transcript, minutes] = await Promise.all([
        Api.getTranscript(this.state.meetingId),
        Api.getLatestMinutes(this.state.meetingId),
      ]);
      Transcript.setAll(transcript);
      if (minutes) Minutes.render(minutes);
      await Speakers.refresh();

      this._setStatus(`会議は終了しました(ID: ${this.state.meetingId})`);
      document.getElementById("start-meeting-btn").disabled = false;
    } catch (err) {
      console.error(err);
      this._setStatus(`エラー: ${err.message}`);
      document.getElementById("stop-meeting-btn").disabled = false;
    }
  },
};

document.addEventListener("DOMContentLoaded", () => App.init());
