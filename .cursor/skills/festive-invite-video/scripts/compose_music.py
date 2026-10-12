"""Synthesise an original Carnatic-style instrumental (veena or violin + tabla + tambura) as a WAV.

Melodies are written as degree patterns over a pentatonic raga, so the same composition works for
every raga in RAGAS. Adi tala (8 beats = 32 quarter-beat units per cycle).
"""
import argparse
import wave

import numpy as np
from scipy.signal import lfilter

SR = 44100
SA = 277.18  # C#4; tabla dayan is tuned here, veena plays an octave lower

# scale: semitones of the five swaras; stable: swaras sung plain (no gamaka); drone: tambura's first string
RAGAS = {
    "hindolam": {"scale": [0, 3, 5, 8, 10], "stable": {0, 5}, "drone": 5},
    "hamsadhwani": {"scale": [0, 2, 4, 7, 11], "stable": {0, 7}, "drone": 7},
    "mohanam": {"scale": [0, 2, 4, 7, 9], "stable": {0, 7}, "drone": 7},
}

# (scale degree, units). Degree 0 = Sa, 5 = upper Sa, -1 = lower Ni etc.
PHRASES = [
    [(0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (5, 8), (4, 2), (3, 2)],
    [(2, 2), (3, 2), (4, 2), (5, 2), (6, 4), (5, 4), (4, 2), (3, 2), (2, 4), (1, 4), (0, 4)],
    [(d, 2) for d in [0, 1, 2, 3, 4, 5, 6, 7, 7, 6, 5, 4, 3, 2, 1, 0]],
    [(3, 4), (4, 2), (5, 2), (4, 4), (3, 4), (2, 2), (3, 2), (1, 4), (2, 4), (0, 4)],
    [(5, 4), (4, 2), (5, 2), (6, 4), (7, 4), (6, 2), (5, 2), (4, 4), (3, 4), (4, 4)],
    [(d, 1) for d in [0, 1, 2, 3, 2, 1, 0, -1, -2, -1, 0, 1, 2, 1, 0, -1,
                      0, 1, 2, 3, 4, 3, 2, 1]] + [(0, 8)],
    [(1, 4), (2, 4), (3, 4), (4, 4), (5, 8), (4, 4), (3, 4)],
    [(d, 2) for d in [0, 1, 2, 3, 4, 5, 6, 7, 7, 6, 5, 4, 3, 2, 1, 0]],
    [(3, 2), (4, 2), (5, 2), (6, 2), (7, 4)] * 2 + [(3, 2), (4, 2), (5, 2), (6, 2)],
]
ENDING = [(5, 8), (4, 2), (3, 2), (2, 2), (1, 2), (0, 16)]


class Mixer:
    def __init__(self, seconds):
        self.n = int(SR * seconds)
        self.L = np.zeros(self.n)
        self.R = np.zeros(self.n)

    def add(self, sig, t0, gain=1.0, pan=0.0):
        i = int(t0 * SR)
        if i >= self.n:
            return
        sig = sig[: self.n - i] * gain
        self.L[i:i + len(sig)] += sig * np.sqrt((1 - pan) / 2)
        self.R[i:i + len(sig)] += sig * np.sqrt((1 + pan) / 2)


def tt(d):
    return np.arange(int(d * SR)) / SR


def peaking(x, f0, gain_db, q):
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * a, -2 * np.cos(w), 1 - al * a])
    den = np.array([1 + al / a, -2 * np.cos(w), 1 - al / a])
    return lfilter(b / den[0], den / den[0], x)


def lowpass(x, fc):
    k = np.exp(-2 * np.pi * fc / SR)
    return lfilter([1 - k], [1, -k], x)


def highpass(x, fc):
    return x - lowpass(x, fc)


def degree_to_semi(raga, d):
    return raga["scale"][d % 5] + 12 * (d // 5)


def build_notes(raga, n_cycles, unit):
    body = [PHRASES[i % len(PHRASES)] for i in range(n_cycles - 1)] + [ENDING]
    notes, t = [], 0.0
    for cyc in body:
        assert sum(u for _, u in cyc) == 32, cyc
        for d, u in cyc:
            notes.append((t, u * unit, d))
            t += u * unit
    return notes


def pitch_curve(raga, notes, unit, n, gamaka_on_stable_vibrato):
    T = np.arange(n) / SR
    semi = np.zeros(n)
    for ts, dur, d in notes:
        a, b = int(ts * SR), min(int((ts + dur) * SR), n)
        lt = T[a:b] - ts
        s = degree_to_semi(raga, d)
        curve = np.full(b - a, float(s))
        if dur >= 4 * unit and (s % 12) not in raga["stable"]:
            up = degree_to_semi(raga, d + 1) - s
            on = np.clip((lt - 0.04) / 0.03, 0, 1)
            curve += on * 0.65 * up * (0.5 - 0.5 * np.cos(2 * np.pi * 6.5 * (lt - 0.04)))
        elif dur >= 4 * unit and gamaka_on_stable_vibrato:
            curve += 0.12 * np.clip((lt - 0.15) / 0.1, 0, 1) * np.sin(2 * np.pi * 5.5 * lt)
        semi[a:b] = curve
    k = int(0.018 * SR)
    return np.convolve(semi, np.ones(k) / k, mode="same")


def render_veena(notes, semi, seconds, unit, rng):
    n = len(semi)
    T = np.arange(n) / SR
    f = SA / 2 * 2 ** (semi / 12)
    ph = 2 * np.pi * np.cumsum(f) / SR
    hs = np.arange(1, 29)
    weights = np.abs(np.sin(np.pi * hs * 0.13)) / hs ** 1.15
    phis = rng.uniform(0, 2 * np.pi, len(hs))
    xf = 0.008
    out = np.zeros(n)
    starts = [ts for ts, _, _ in notes]
    for i, ts in enumerate(starts):
        te = starts[i + 1] if i + 1 < len(starts) else seconds
        a, b = int(ts * SR), min(int((te + xf) * SR), n)
        lt = T[a:b] - ts
        seg = np.zeros(b - a)
        for h, w, phi in zip(hs, weights, phis):
            mask = np.clip((10000 - h * f[a:b]) / 1500, 0, 1)
            seg += w * mask * np.exp(-lt * (0.9 + 0.42 * h)) * np.sin(h * ph[a:b] * (1 + 0.00006 * h * h) + phi)
        vel = rng.uniform(0.85, 1.0) * (1.1 if round(ts / unit) % 4 == 0 else 1.0)
        pick = highpass(rng.standard_normal(b - a), 2500) * np.exp(-lt / 0.002) * 0.12
        seg = (seg + pick) * vel * np.minimum(1, lt / 0.0015)
        if i + 1 < len(starts):
            seg *= np.clip((te + xf - T[a:b]) / xf, 0, 1)
        out[a:b] += seg
    out = np.tanh(1.4 * out / np.abs(out).max()) * np.clip((seconds - T) / 1.0, 0, 1)
    out = highpass(out, 70)
    for f0, g, q in [(180, 5, 1.4), (420, 3, 1.6), (1500, 2, 1.2), (3200, -3, 1.0)]:
        out = peaking(out, f0, g, q)
    out = lowpass(out, 6500)
    return out / np.abs(out).max()


def render_violin(notes, semi, seconds, rng):
    n = len(semi)
    T = np.arange(n) / SR
    amp = np.zeros(n)
    for ts, dur, _ in notes:
        a, b = int(ts * SR), min(int((ts + dur) * SR), n)
        amp[a:b] = 1 - 0.35 * np.exp(-(T[a:b] - ts) / 0.02)
    end_t = notes[-1][0] + notes[-1][1]
    amp *= np.minimum(1, T / 0.03) * np.clip((end_t - T) / 0.8, 0, 1) * (0.85 + 0.15 * np.sin(2 * np.pi * T / 4))
    f = SA * 2 ** (semi / 12)
    ph = 2 * np.pi * np.cumsum(f) / SR
    out = np.zeros(n)
    for h in range(1, 36):
        out += np.clip((11000 - h * f) / 1500, 0, 1) * np.sin(h * ph) / h
    out = (out + highpass(lowpass(rng.standard_normal(n), 6000), 2000) * 0.04) * amp
    out = highpass(out, 190)
    for f0, g, q in [(290, 6, 2.0), (460, 4, 2.0), (1100, 3, 1.5), (2800, 6, 1.2), (4500, -4, 1.0)]:
        out = peaking(out, f0, g, q)
    out = lowpass(out, 7500)
    return out / np.abs(out).max()


def tabla(mix, n_cycles, unit, rng):
    def dayan(fr, decay, click=1.0):
        t = tt(0.6)
        body = sum(a * np.sin(2 * np.pi * fr * m * t) for m, a in [(1, 1), (2, 0.6), (3, 0.4), (4, 0.25)])
        return body * np.exp(-t / decay) + rng.standard_normal(len(t)) * np.exp(-t / 0.003) * 0.6 * click

    def bayan(strong=1.0):
        t = tt(0.6)
        fr = 75 + 50 * np.exp(-t / 0.04)
        return np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t / 0.2) * 1.4 * strong

    def ka():
        t = tt(0.08)
        return np.convolve(rng.standard_normal(len(t)), np.ones(10) / 10, mode="same") * np.exp(-t / 0.015) * 2.0

    bols = {
        "dha": lambda: dayan(SA, 0.16) + bayan(),
        "dhi": lambda: dayan(SA, 0.08, 0.7) + bayan(0.8),
        "ge": lambda: bayan(0.9),
        "na": lambda: dayan(SA, 0.14),
        "ta": lambda: dayan(SA, 0.14),
        "ti": lambda: dayan(SA, 0.035, 1.3),
        "ki": lambda: dayan(SA, 0.035, 1.3),
        "ra": lambda: dayan(SA, 0.03, 0.9) * 0.7,
        "ka": ka,
    }
    theka = "dha ti ge na dha ti dha ge na ti ka dhi na dha ge na".split()
    fill = "ti ra ki ta dha ti ra ki ta dha - ti ra ki ta dha".split()
    cycle = 32 * unit
    fills = {c for c in range(1, n_cycles - 1) if c % 3 == 0} | ({n_cycles - 2} if n_cycles > 2 else set())
    for c in range(n_cycles):
        t0 = c * cycle
        if c == n_cycles - 1:
            mix.add(bols["dha"](), t0, 0.32)
            continue
        for s, bol in enumerate(theka):
            if c in fills and s >= 8:
                break
            mix.add(bols[bol](), t0 + s * 2 * unit, 0.30 if s == 0 else 0.22, -0.1)
        if c in fills:
            for s, bol in enumerate(fill):
                if bol != "-":
                    mix.add(bols[bol](), t0 + 16 * unit + s * unit, 0.27 if bol == "dha" else 0.20, -0.1)


def tambura(mix, raga, n_cycles, unit):
    def pluck(fr, d=2.2):
        t = tt(d)
        out = np.zeros_like(t)
        for h in range(1, 20):
            shimmer = 1 + 0.5 * np.sin(2 * np.pi * (0.7 + 0.13 * h) * t + h)
            out += (1 / h) * shimmer * np.exp(-t * (1.0 + 0.1 * h)) * np.sin(2 * np.pi * fr * h * t)
        return out * np.minimum(1, t / 0.01)

    cycle = 32 * unit
    for c in range(n_cycles):
        for j, s in enumerate([raga["drone"] - 12, 0, 0, -12]):
            mix.add(pluck(SA / 2 * 2 ** (s / 12)), c * cycle + j * cycle / 4, 0.05, 0.3)


def veena_talam(mix, n_cycles, unit):
    def string(fr, d=1.6):
        t = tt(d)
        out = sum((1 / h ** 1.3) * np.exp(-t * (1.6 + 0.6 * h)) * np.sin(2 * np.pi * fr * h * t) for h in range(1, 12))
        return out * np.minimum(1, t / 0.002)

    for c in range(n_cycles - 1):
        for beat in (0, 4):
            sig = string(SA / 2) + 0.7 * string(SA)
            mix.add(sig, c * 32 * unit + beat * 4 * unit, 0.07 if beat else 0.09, 0.2)


def reverb(x, rng):
    t = tt(1.2)
    ir = rng.standard_normal(len(t)) * np.exp(-t / 0.3)
    ir[0] = 0
    ir /= np.abs(ir).sum() / 6
    size = 1 << (len(x) + len(ir) - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return x + 0.2 * wet


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", help="output .wav path")
    ap.add_argument("--raga", choices=sorted(RAGAS), default="hindolam")
    ap.add_argument("--instrument", choices=["veena", "violin"], default="veena")
    ap.add_argument("--cycle", type=float, default=2.4, help="seconds per 8-beat Adi tala cycle (lower = faster)")
    ap.add_argument("--seconds", type=float, default=24.0)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    raga = RAGAS[args.raga]
    unit = args.cycle / 32
    n_cycles = max(2, round(args.seconds / args.cycle))
    seconds = n_cycles * args.cycle
    mix = Mixer(seconds)

    notes = build_notes(raga, n_cycles, unit)
    semi = pitch_curve(raga, notes, unit, mix.n, gamaka_on_stable_vibrato=args.instrument == "violin")
    if args.instrument == "veena":
        lead = render_veena(notes, semi, seconds, unit, rng)
        mix.add(lead, 0, 0.46, 0.1)
        veena_talam(mix, n_cycles, unit)
    else:
        lead = render_violin(notes, semi, seconds, rng)
        mix.add(lead, 0, 0.42, 0.2)
    tabla(mix, n_cycles, unit, rng)
    tambura(mix, raga, n_cycles, unit)

    T = np.arange(mix.n) / SR
    env = np.minimum(1, T / 0.05) * np.clip((seconds - T) / 1.0, 0, 1)
    out = np.stack([reverb(mix.L, rng), reverb(mix.R, rng)], 1) * env[:, None]
    out = np.tanh(out / np.abs(out).max() * 1.6) / np.tanh(1.6) * 0.9

    with wave.open(args.output, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((out * 32767).astype("<i2").tobytes())
    print(f"{args.raga} / {args.instrument}: {n_cycles} cycles x {args.cycle}s = {seconds:.1f}s, "
          f"{len(notes)} notes -> {args.output}")


if __name__ == "__main__":
    main()
