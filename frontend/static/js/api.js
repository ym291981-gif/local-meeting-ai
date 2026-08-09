// バックエンドREST API / WebSocketとの通信をまとめたヘルパー。
const Api = {
  async _json(res) {
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`APIエラー(${res.status}): ${text}`);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  createMeeting(title) {
    return fetch("/api/meetings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title || "無題の会議" }),
    }).then(this._json);
  },

  stopMeeting(meetingId) {
    return fetch(`/api/meetings/${meetingId}/stop`, { method: "POST" }).then(this._json);
  },

  getTranscript(meetingId) {
    return fetch(`/api/meetings/${meetingId}/transcript`).then(this._json);
  },

  correctUtterance(meetingId, utteranceId, payload) {
    return fetch(`/api/meetings/${meetingId}/utterances/${utteranceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(this._json);
  },

  getSpeakers(meetingId) {
    return fetch(`/api/meetings/${meetingId}/speakers`).then(this._json);
  },

  assignSpeaker(meetingId, speakerId, participantName) {
    return fetch(`/api/meetings/${meetingId}/speakers/${speakerId}/assign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_name: participantName }),
    }).then(this._json);
  },

  mergeSpeaker(meetingId, speakerId, intoSpeakerId) {
    return fetch(`/api/meetings/${meetingId}/speakers/${speakerId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ into_speaker_id: Number(intoSpeakerId) }),
    }).then(this._json);
  },

  getParticipants(meetingId) {
    return fetch(`/api/meetings/${meetingId}/participants`).then(this._json);
  },

  addParticipant(meetingId, name) {
    return fetch(`/api/meetings/${meetingId}/participants`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then(this._json);
  },

  deleteParticipant(meetingId, participantId) {
    return fetch(`/api/meetings/${meetingId}/participants/${participantId}`, {
      method: "DELETE",
    }).then(this._json);
  },

  getLatestMinutes(meetingId) {
    return fetch(`/api/meetings/${meetingId}/minutes/latest`).then((res) => {
      if (res.status === 404) return null;
      return this._json(res);
    });
  },

  editMinutes(meetingId, payload) {
    return fetch(`/api/meetings/${meetingId}/minutes/latest`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(this._json);
  },

  connectWebSocket(meetingId, handlers) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/meetings/${meetingId}`);
    ws.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (data.type === "utterance" && handlers.onUtterance) handlers.onUtterance(data.utterance);
      if (data.type === "minutes" && handlers.onMinutes) handlers.onMinutes(data.minutes);
      if (data.type === "meeting_ended" && handlers.onMeetingEnded) handlers.onMeetingEnded();
    };
    return ws;
  },
};
