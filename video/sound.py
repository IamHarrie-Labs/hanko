"""Original music bed and sound effects, synthesised so nothing needs a licence.

Writes public/sfx/*.wav and public/music.wav at 48 kHz.
"""
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 48000
OUT = Path("public/sfx")
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)


def t(seconds):
    return np.arange(int(SR * seconds)) / SR


def lowpass(x, hz, order=2):
    return sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x)


def highpass(x, hz, order=2):
    return sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x)


def bandpass(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def save(name, x, peak=0.9):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = x / (np.max(np.abs(x)) + 1e-9) * peak
    wavfile.write(OUT / name if name != "music.wav" else Path("public") / name, SR, (x * 32767).astype(np.int16))


def env(n, attack, release, curve=3.0):
    e = np.ones(n)
    a = min(n, max(1, int(attack * SR)))
    r = min(n, max(1, int(release * SR)))
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


# --- stamp: a felt-and-wood thud ------------------------------------------
x = t(0.9)
sweep = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-x * 9) + 38) / SR)
body = sweep * np.exp(-x * 6)
click = lowpass(rng.normal(size=len(x)), 2500) * np.exp(-x * 60) * 0.6
paper = bandpass(rng.normal(size=len(x)), 900, 4000) * np.exp(-x * 25) * 0.25
save("stamp.wav", body + click + paper)

# --- whoosh: filtered noise swelling past --------------------------------
x = t(0.7)
noise = rng.normal(size=len(x))
shape = np.sin(np.pi * np.clip(x / 0.7, 0, 1)) ** 2
lo = bandpass(noise, 300, 1400) * shape
hi = bandpass(noise, 1800, 6000) * shape ** 3 * 0.5
pan = np.linspace(-1, 1, len(x))
w = lo + hi
save("whoosh.wav", np.stack([w * (1 - pan) / 2 + w * 0.3, w * (1 + pan) / 2 + w * 0.3], axis=1), 0.7)

# --- tick: a dry key click ------------------------------------------------
x = t(0.05)
save("tick.wav", highpass(rng.normal(size=len(x)), 2000) * np.exp(-x * 220), 0.5)

# --- pop: a soft rounded blip for things landing --------------------------
x = t(0.18)
save("pop.wav", np.sin(2 * np.pi * (520 + 380 * np.exp(-x * 40)) * x) * np.exp(-x * 26), 0.6)

# --- chime: two clean partials for "held" / "verified" --------------------
x = t(1.2)
c = (np.sin(2 * np.pi * 1318.5 * x) + 0.5 * np.sin(2 * np.pi * 1975.5 * x)) * np.exp(-x * 4.5)
save("chime.wav", c * env(len(x), 0.002, 0.3), 0.45)

# --- glitch: the seal breaking --------------------------------------------
x = t(0.5)
g = np.sign(np.sin(2 * np.pi * 70 * x)) * (rng.random(len(x)) > 0.5)
crush = np.round(rng.normal(size=len(x)) * 4) / 4
save("glitch.wav", lowpass(g * 0.6 + crush * 0.4, 5000) * np.exp(-x * 5), 0.6)

# --- riser: tension into the reveal ---------------------------------------
x = t(2.0)
r = bandpass(rng.normal(size=len(x)), 500, 7000) * (x / 2.0) ** 2.5
tone = np.sin(2 * np.pi * np.cumsum(200 + 600 * (x / 2.0) ** 2) / SR) * (x / 2.0) ** 3 * 0.4
save("riser.wav", r + tone, 0.55)

# --- music: a warm pad with a slow pulse ------------------------------------
BPM = 92
beat = 60 / BPM
bars = 44
length = bars * 4 * beat
x = t(length)
# A minor, F major, C major, G major: one chord per two bars.
chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
pad = np.zeros(len(x))
seg = int(8 * beat * SR)
for i in range(0, len(x), seg):
    n = min(seg, len(x) - i)
    xs = np.arange(n) / SR
    chord = chords[(i // seg) % 4]
    s = np.zeros(n)
    for f in chord:
        for detune in (-0.25, 0.0, 0.25):
            ph = rng.random() * 2 * np.pi
            s += (2 * ((f * (1 + detune / 100) * xs + ph / (2 * np.pi)) % 1) - 1) * 0.12
    s = lowpass(s, 900) * env(n, 1.2, 1.4, 1.5)
    pad[i:i + n] += s
lfo = 0.75 + 0.25 * np.sin(2 * np.pi * x / (beat * 8))
pad *= lfo

bass = np.zeros(len(x))
pulse = np.zeros(len(x))
for k in range(int(length / beat)):
    start = int(k * beat * SR)
    n = min(int(beat * SR), len(x) - start)
    xs = np.arange(n) / SR
    root = chords[(k // 8) % 4][0] / 2
    bass[start:start + n] += np.sin(2 * np.pi * root * xs) * np.exp(-xs * 3.5) * 0.5
    kick = np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-xs * 30)) / SR) * np.exp(-xs * 9)
    pulse[start:start + n] += kick * (0.55 if k % 2 == 0 else 0.3)
    if k % 2 == 1:
        hat = highpass(rng.normal(size=n), 7000) * np.exp(-xs * 70) * 0.12
        pulse[start:start + n] += hat
# Fade the beat in after the hook so the opening breathes, then hold.
beat_in = np.clip((x - 6.0) / 4.0, 0, 1)
music = pad * 0.9 + lowpass(bass, 400) * 0.8 + pulse * beat_in * 0.7
music = lowpass(music, 9000)
music *= env(len(x), 2.5, 4.0, 1.0)
stereo = np.stack([music + 0.15 * np.roll(pad, 240), music + 0.15 * np.roll(pad, -240)], axis=1)
save("music.wav", stereo, 0.8)
print("music", round(length, 1), "s")
