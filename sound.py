"""低音量短音效；启动时生成 PCM，无外部音频文件或额外依赖。"""
from array import array
import logging
import math
import random
import pygame as pg


def samples(kind, rate=44100, channels=1):
    """轻巧的纸牌点击与柔和的按钮确认音；起止淡入淡出防爆音。"""
    duration = .045 if kind == "card" else .075
    frames = round(rate * duration)
    rng = random.Random(17)
    pcm = array("h")
    for i in range(frames):
        t = i / rate
        envelope = min(1, t / .003) * math.exp(-t * 55) * min(1, (frames-1-i)/(rate*.008))
        if kind == "card":
            wave = .62*math.sin(2*math.pi*1050*t) + .38*rng.uniform(-1, 1)
        else:
            wave = .75*math.sin(2*math.pi*660*t) + .25*math.sin(2*math.pi*990*t)
        value = round(32767 * .20 * envelope * wave)
        pcm.extend([value] * channels)
    return pcm


class Sounds:
    def __init__(self):
        self.available = False
        self.enabled = True
        self.sounds = {}
        try:
            pg.mixer.init(frequency=44100, size=-16, channels=1, buffer=512, allowedchanges=0)
            rate, size, channels = pg.mixer.get_init()
            if size != -16:
                raise ValueError("音频格式不兼容")
            for name in ("card", "button"):
                self.sounds[name] = pg.mixer.Sound(buffer=samples(name, rate, channels).tobytes())
            self.channels = {"card": pg.mixer.Channel(0), "button": pg.mixer.Channel(1)}
            self.available = True
        except (pg.error, ValueError):
            logging.warning("音效设备不可用，继续以静音模式运行。", exc_info=True)

    @property
    def label(self):
        if not self.available:
            return "音效不可用"
        return "音效：开" if self.enabled else "音效：关"

    def play(self, kind):
        if self.available and self.enabled:
            try:
                self.channels[kind].play(self.sounds[kind])
            except pg.error:
                self.available = False
                logging.warning("音频播放中断，已转为静音。", exc_info=True)

    def toggle(self):
        self.enabled = not self.enabled
        if self.available:
            if self.enabled:
                self.play("button")
            else:
                for channel in self.channels.values():
                    channel.stop()
