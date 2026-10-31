"""RTTY decoder (Baudot/ITA2, async 5-bit) for DWD weather text broadcasts.

DWD Pinneberg sends 50 baud, 450 Hz shift on 4583, 7646 and 10100.8 kHz.
The two tones are found automatically in the audio, and both polarities are
tried, so the exact dial frequency does not matter much. Needs numpy.
"""
import numpy as np

LTRS = ["", "E", "\n", "A", " ", "S", "I", "U", "\r", "D", "R", "J", "N", "F", "C", "K",
        "T", "Z", "L", "W", "H", "Y", "P", "Q", "O", "B", "G", None, "M", "X", "V", None]
FIGS = ["", "3", "\n", "-", " ", "'", "8", "7", "\r", "", "4", "", ",", "!", ":", "(",
        "5", "+", ")", "2", "#", "6", "0", "1", "9", "?", "&", None, ".", "/", "=", None]
FIGS_CODE, LTRS_CODE = 27, 31


def find_tones(audio, fs, shift=450.0, lo=300.0, hi=3000.0):
    """Return (space_hz, mark_hz): the strongest pair of spectral peaks `shift` apart."""
    x = np.asarray(audio, dtype=np.float64)
    n = 1 << int(np.log2(min(len(x), fs * 8)))
    segs = [x[i:i + n] for i in range(0, len(x) - n + 1, n)] or [np.pad(x, (0, n - len(x)))]
    spec = np.zeros(n // 2 + 1)
    for s in segs:
        spec += np.abs(np.fft.rfft(s * np.hanning(n))) ** 2
    freqs = np.fft.rfftfreq(n, 1 / fs)
    df = freqs[1]
    k = int(round(shift / df))
    sm = np.convolve(spec, np.ones(max(1, int(20 / df))), mode="same")
    best, bi = -1, 0
    for i in range(int(lo / df), min(len(sm) - k, int(hi / df))):
        v = min(sm[i], sm[i + k])  # both tones must be present
        if v > best:
            best, bi = v, i
    return freqs[bi], freqs[bi + k]


def _tone_env(x, fs, f, baud):
    n = np.arange(len(x))
    z = x * np.exp(-2j * np.pi * f / fs * n)
    m = max(3, int(fs / baud * 0.6))  # moving average ~0.6 bit
    return np.abs(np.convolve(z, np.ones(m) / m, mode="same"))


def bits_signal(audio, fs, space, mark, baud=50.0):
    """+1 where mark is stronger, -1 for space."""
    x = np.asarray(audio, dtype=np.float64)
    d = _tone_env(x, fs, mark, baud) - _tone_env(x, fs, space, baud)
    return np.sign(d)


def uart(sig, fs, baud=50.0, stop_bits=1.5):
    """Asynchronous framing: idle/stop = mark (+1), start bit = space (-1), 5 data bits LSB first."""
    bit = fs / baud
    n = len(sig)
    edges = np.flatnonzero((sig[1:] < 0) & (sig[:-1] > 0)) + 1  # mark -> space transitions
    codes = []
    next_ok = 0
    for i in edges:
        if i < next_ok or i + bit * 7 >= n:
            continue
        if sig[int(i + bit / 2)] > 0:  # start bit must still be space halfway
            continue
        if sig[int(i + bit * 6.5)] <= 0:  # stop bit must be mark
            continue
        val = 0
        for b in range(5):
            if sig[int(i + bit * (1.5 + b))] > 0:
                val |= 1 << b
        codes.append(val)
        next_ok = i + bit * (6 + stop_bits) - bit / 2
    return codes


def baudot_to_text(codes, unshift_on_space=True):
    out, figs = [], False
    for c in codes:
        if c == FIGS_CODE:
            figs = True
        elif c == LTRS_CODE:
            figs = False
        else:
            ch = (FIGS if figs else LTRS)[c]
            if ch:
                out.append(ch)
            if ch == " " and unshift_on_space:
                figs = False
    return "".join(out).replace("\r", "")


def _score(text):
    if not text:
        return 0
    good = sum(ch.isalpha() or ch in " \n" for ch in text)
    words = sum(1 for w in text.split() if 2 <= len(w) <= 12)
    return good / len(text) + words / max(1, len(text.split()))


def decode(audio, fs, shift=450.0, baud=50.0):
    """Audio -> (text, info dict). Tries both polarities and keeps the more readable one."""
    space, mark = find_tones(audio, fs, shift)
    sig = bits_signal(audio, fs, space, mark, baud)
    best = ("", -1, None)
    for pol in (1, -1):
        text = baudot_to_text(uart(sig * pol, fs, baud))
        s = _score(text)
        if s > best[1]:
            best = (text, s, pol)
    text, score, pol = best
    lo, hi = (space, mark) if pol == 1 else (mark, space)
    return text, {"mark_hz": round(float(hi if pol == 1 else lo)), "space_hz": round(float(lo if pol == 1 else hi)),
                  "quality": round(float(score), 2)}


def encode(text, fs, mark=2125.0, space=1675.0, baud=50.0, stop_bits=1.5, lead_s=1.0):
    """Text -> RTTY audio. Used by the tests."""
    rev_l = {c: i for i, c in enumerate(LTRS) if c}
    rev_f = {c: i for i, c in enumerate(FIGS) if c}
    codes, figs = [LTRS_CODE], False
    for ch in text.upper():
        if ch == " ":
            codes.append(4)
            figs = False  # receivers "unshift on space"
        elif ch in rev_l:
            if figs and ch != " ":
                codes.append(LTRS_CODE)
                figs = False
            codes.append(rev_l[ch])
        elif ch in rev_f:
            if not figs:
                codes.append(FIGS_CODE)
                figs = True
            codes.append(rev_f[ch])
    bits = [1] * int(lead_s * baud)
    for c in codes:
        bits += [0] + [(c >> b) & 1 for b in range(5)] + [1] * 2  # 2 stop bits worth, sliced by duration below
    edges = np.round(np.arange(len(bits) + 1) * fs / baud).astype(int)
    f = np.concatenate([np.full(edges[i + 1] - edges[i], mark if b else space) for i, b in enumerate(bits)])
    phase = 2 * np.pi * np.cumsum(f) / fs
    return np.sin(phase) * 0.5
