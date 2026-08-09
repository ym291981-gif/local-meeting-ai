"""Windows内部音声(WASAPIループバック)取得。

要件定義書 第15章:
    - PC内部音声を取得できる
    - マイクからZoom音声を拾わない
    - 会議相手へアプリ側の音声が送信されない(あくまで「聴く」側の録音)
    - Zoomホスト権限を必要としない

PyAudioWPatch(https://github.com/s0d3s/PyAudioWPatch)を用いて、既定の
再生デバイス(スピーカー/ヘッドフォン)のループバックデバイスから録音する。
Zoom会議中の音声・デモ音声再生時の音声のいずれも、この経路で同一に取得できる
(要件定義書 第6章・第36.2章: Audio SourceとAudio Captureを疎結合にする)。
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from types import TracebackType

import numpy as np
import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)


@dataclass
class LoopbackDeviceInfo:
    index: int
    name: str
    sample_rate: int
    channels: int


def list_loopback_devices() -> list[LoopbackDeviceInfo]:
    """利用可能なWASAPIループバックデバイス(内部音声取得元)の一覧を返す。"""
    devices: list[LoopbackDeviceInfo] = []
    with pyaudio.PyAudio() as pa:
        for info in pa.get_loopback_device_info_generator():
            devices.append(
                LoopbackDeviceInfo(
                    index=info["index"],
                    name=info["name"],
                    sample_rate=int(info["defaultSampleRate"]),
                    channels=info["maxInputChannels"],
                )
            )
    return devices


def get_default_loopback_device() -> LoopbackDeviceInfo:
    """既定の再生デバイス(スピーカー等)に対応するループバックデバイスを返す。"""
    with pyaudio.PyAudio() as pa:
        info = pa.get_default_wasapi_loopback()
    return LoopbackDeviceInfo(
        index=info["index"],
        name=info["name"],
        sample_rate=int(info["defaultSampleRate"]),
        channels=info["maxInputChannels"],
    )


class WasapiLoopbackCapture:
    """PC内部音声を継続的に取得し、numpy配列(float32, shape=[frames, channels])を
    キューへ供給するキャプチャクラス。

    with構文で開始/停止し、`iter_frames()` で取得した音声フレームを順次受け取る。
    """

    _FRAMES_PER_BUFFER = 1024

    def __init__(self, device: LoopbackDeviceInfo | None = None) -> None:
        self._pa = pyaudio.PyAudio()
        self._device = device or self._resolve_default_device()
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._stream: pyaudio.Stream | None = None
        self._stopped = threading.Event()

    def _resolve_default_device(self) -> LoopbackDeviceInfo:
        info = self._pa.get_default_wasapi_loopback()
        return LoopbackDeviceInfo(
            index=info["index"],
            name=info["name"],
            sample_rate=int(info["defaultSampleRate"]),
            channels=info["maxInputChannels"],
        )

    @property
    def sample_rate(self) -> int:
        return self._device.sample_rate

    @property
    def channels(self) -> int:
        return self._device.channels

    def _callback(self, in_data, frame_count, time_info, status):  # noqa: ANN001
        if self._stopped.is_set():
            return (None, pyaudio.paComplete)
        audio = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels)
        self._queue.put(audio.copy())
        return (None, pyaudio.paContinue)

    def start(self) -> None:
        logger.info(
            "内部音声キャプチャを開始します: device=%s sample_rate=%s channels=%s",
            self._device.name,
            self._device.sample_rate,
            self._device.channels,
        )
        self._stopped.clear()
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._device.channels,
            rate=self._device.sample_rate,
            frames_per_buffer=self._FRAMES_PER_BUFFER,
            input=True,
            input_device_index=self._device.index,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def stop(self) -> None:
        self._stopped.set()
        if self._stream is not None and self._stream.is_active():
            self._stream.stop_stream()
        if self._stream is not None:
            self._stream.close()
        self._queue.put(None)
        self._pa.terminate()
        logger.info("内部音声キャプチャを停止しました")

    def iter_frames(self):
        """取得済みの音声フレーム(numpy配列)を順次返すジェネレータ。stop()後にNoneで終了する。"""
        while True:
            item = self._queue.get()
            if item is None:
                return
            yield item

    def __enter__(self) -> "WasapiLoopbackCapture":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
