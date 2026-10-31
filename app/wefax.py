"""HF weather fax (radiofax) decoder: audio in, grayscale image out.

Standard WMO/ITU radiofax as sent by DWD Pinneberg (3855, 7880, 13882.5 kHz):
FM subcarrier, black = centre - 400 Hz, white = centre + 400 Hz, 120 lines per
minute, IOC 576 (1810 pixels per line). A transmission starts with a 300 Hz
black/white "start tone" for ~5 s, then ~30 s of phasing lines (a short white
pulse at the start of each line), then the chart, then a 450 Hz stop tone.

The receiver is in USB mode, so the audio centre frequency is
(assigned frequency - dial frequency) e.g. 3855.0 kHz assigned, dial 3853 kHz
-> centre 2000 Hz.

Needs numpy.
"""
import math
import struct
import zlib

import numpy as np

LPM = 120
IOC = 576
WIDTH = int(round(IOC * math.pi))  # 1810 pixels
DEVIATION = 400.0


def _lowpass(n_taps, cutoff, fs):
    t = np.arange(n_taps) - (n_taps - 1) / 2
    h = np.sinc(2 * cutoff / fs * t) * np.hamming(n_taps)
    return h / h.sum()


def demodulate(audio, fs, centre, chunk=1 << 18):
    """Audio samples -> level 0 (black) .. 1 (white) at the same sample rate.

    Works in chunks with float32 so a 20-minute recording fits in the Pi Zero's RAM."""
    x = np.asarray(audio, dtype=np.float32)
    x = x - np.float32(x.mean())
    h = _lowpass(65, 1100.0, fs).astype(np.complex64)
    pad = 64
    f = np.empty(len(x), np.float32)
    w = 2 * np.pi * centre / fs
    for a in range(0, len(x), chunk):
        b = min(len(x), a + chunk)
        a0, b0 = max(0, a - pad), min(len(x), b + pad)
        n = np.arange(a0, b0, dtype=np.float64)
        z = (x[a0:b0] * np.exp(-1j * w * n)).astype(np.complex64)
        z = np.convolve(z, h, mode="same")
        dphi = np.angle(z[1:] * np.conj(z[:-1]))
        seg = np.concatenate([[0.0], dphi]).astype(np.float32) * np.float32(fs / (2 * np.pi))
        f[a:b] = seg[a - a0:a - a0 + (b - a)]
    level = (f + DEVIATION) / (2 * DEVIATION)
    # smooth slightly (pixel time is ~0.28 ms)
    level = np.convolve(level, np.ones(3, np.float32) / 3, mode="same")
    return np.clip(level, 0.0, 1.0).astype(np.float32)


def auto_centre(audio, fs, nominal, search=350.0):
    """Find the real fax centre frequency: radio crystals can be a few hundred Hz off
    on shortwave. Every fax has full black and full white (the phasing lines are
    almost all black with a white pulse, charts are black on white), so the
    centre is midway between the low and high ends of the measured tone."""
    x = np.asarray(audio, dtype=np.float32)
    if len(x) < fs * 5:
        return float(nominal)
    # wide demodulation around the nominal centre, scaled back to Hz
    z = _inst_freq(x[: int(fs * 600)], fs, nominal)  # the first 10 minutes are plenty
    z = np.convolve(z, np.ones(9) / 9, mode="same")
    lo, hi = np.percentile(z, [4, 96])
    if hi - lo < 1.2 * DEVIATION or hi - lo > 3.0 * DEVIATION:
        return float(nominal)  # not enough black and white to tell
    off = (lo + hi) / 2
    return float(nominal + max(-search, min(search, off)))


def _inst_freq(x, fs, centre, chunk=1 << 18):
    """Instantaneous frequency offset from `centre` in Hz, not clipped (float32)."""
    x = np.asarray(x, dtype=np.float32)
    x = x - np.float32(x.mean())
    h = _lowpass(65, 1500.0, fs).astype(np.complex64)
    out = np.empty(len(x), np.float32)
    w = 2 * np.pi * centre / fs
    pad = 64
    for a in range(0, len(x), chunk):
        b = min(len(x), a + chunk)
        a0, b0 = max(0, a - pad), min(len(x), b + pad)
        n = np.arange(a0, b0, dtype=np.float64)
        z = np.convolve((x[a0:b0] * np.exp(-1j * w * n)).astype(np.complex64), h, mode="same")
        d = np.concatenate([[0.0], np.angle(z[1:] * np.conj(z[:-1]))]) * (fs / (2 * np.pi))
        out[a:b] = d[a - a0:a - a0 + (b - a)]
    return out


def tone_power(level, fs, freq, win_s=0.5):
    """Relative strength of a black/white alternation at `freq` Hz in each window."""
    win = int(fs * win_s)
    nwin = len(level) // win
    out = np.zeros(nwin)
    t = np.arange(win)
    ref = np.exp(-2j * np.pi * freq / fs * t)
    for i in range(nwin):
        seg = level[i * win:(i + 1) * win]
        seg = seg - seg.mean()
        energy = np.sum(seg * seg) + 1e-9
        out[i] = abs(np.dot(seg, ref)) ** 2 / (energy * win / 2)
    return out  # ~1.0 for a pure tone, small for picture content


def find_runs(mask, min_len):
    runs, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    return runs


def _sample_lines(level, fs, start, period, n_lines, width=WIDTH):
    """Resample the level signal into an image, `period` samples per line."""
    cols = np.arange(width) / width
    rows = []
    last = len(level) - 1
    for k in range(n_lines):
        pos = start + (k + cols) * period
        if pos[-1] >= last:
            break
        i = pos.astype(np.int64)
        frac = (pos - i).astype(np.float32)
        rows.append(level[i] * (1 - frac) + level[i + 1] * frac)
    return np.array(rows, dtype=np.float32).reshape(-1, width)


def _phase_from_lines(img):
    """Column where lines start, found by correlating with an ideal phasing line
    (5% white pulse, rest black). Returns (column, strength 0..1), sub-pixel."""
    w = img.shape[1]
    prof = img.mean(axis=0)
    prof = prof - prof.mean()
    tmpl = -np.ones(w)
    tmpl[: int(0.05 * w)] = 1.0
    tmpl -= tmpl.mean()
    corr = np.real(np.fft.ifft(np.fft.fft(prof) * np.conj(np.fft.fft(tmpl))))
    i = int(np.argmax(corr))
    y0, y1, y2 = corr[i - 1], corr[i], corr[(i + 1) % w]
    denom = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / denom if denom else 0.0
    strength = corr[i] / (np.linalg.norm(prof) * np.linalg.norm(tmpl) + 1e-9)
    return (i + frac) % w, float(strength)


def decode(audio, fs, centre=1900.0, ppm=0.0, lpm=LPM, find_centre=False):
    """Decode every fax transmission found in the audio.

    Returns a list of dicts: {"image": uint8 array (rows x WIDTH), "start_s": float, "complete": bool}.
    find_centre=True first measures the real centre frequency near `centre`.
    """
    if find_centre:
        centre = auto_centre(audio, fs, centre)
    level = demodulate(audio, fs, centre)
    period = fs * 60.0 / lpm * (1 + ppm * 1e-6)
    win_s = 0.5
    p_start = tone_power(level, fs, 300.0, win_s)
    p_stop = tone_power(level, fs, 450.0, win_s)
    starts = [r for r in find_runs(p_start > 0.35, 4)]
    stops = [r for r in find_runs(p_stop > 0.35, 4)]

    segments = []
    if starts:
        for i, (s0, s1) in enumerate(starts):
            begin = int(s1 * win_s * fs)
            nxt = starts[i + 1][0] * win_s * fs if i + 1 < len(starts) else len(level)
            stop = next((int(a * win_s * fs) for a, _ in stops if a * win_s * fs > begin), None)
            end = int(min(nxt, stop if stop is not None else len(level)))
            segments.append((begin, end, stop is not None))
    else:
        # started listening in the middle of a chart: decode everything we have
        segments.append((0, len(level), False))

    results = []
    for begin, end, complete in segments:
        if end - begin < period * 20:
            continue
        # phasing: the first ~30 s after the start tone (or the whole signal) tells us
        # where lines begin and how far the sound card clock is off
        n_phase = int(min(60, (end - begin) // period))
        img = _sample_lines(level, fs, begin, period, n_phase)
        offset, strength = _phase_from_lines(img)
        # slant: track the pulse position in blocks of phasing lines
        if strength > 0.5 and n_phase >= 40:
            pos = []
            for b in range(0, n_phase - 9, 10):
                o, _ = _phase_from_lines(img[b:b + 10])
                pos.append(o)
            pos = np.unwrap(np.array(pos) / WIDTH * 2 * np.pi) / (2 * np.pi) * WIDTH
            slope = np.polyfit(np.arange(len(pos)) * 10, pos, 1)[0]  # pixels per line
            if abs(slope) < 20:
                period *= 1 + slope / WIDTH
        first = begin + (offset % WIDTH) / WIDTH * period
        n_lines = int((end - first) // period)
        image = _sample_lines(level, fs, first, period, n_lines)
        if len(image) == 0:
            continue
        # drop the phasing lines (they match the phasing template line by line)
        skip = 0
        while skip < min(len(image), 80):
            col, strength = _phase_from_lines(image[skip:skip + 1])
            if strength < 0.5 or min(col, WIDTH - col) > 15:
                break
            skip += 1
        image = image[skip:]
        results.append({"image": (image * 255).astype(np.uint8), "start_s": begin / fs, "complete": complete,
                        "lines": len(image), "centre_hz": round(float(centre))})
    return results


def write_png(path, img):
    """Grayscale uint8 array -> PNG file (no Pillow needed)."""
    h, w = img.shape
    raw = b"".join(b"\x00" + img[r].tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def downscale(img, width=905):
    """Halve the width (1810 -> 905) and height by averaging, for the small screen."""
    f = max(1, img.shape[1] // width)
    h = (img.shape[0] // f) * f
    w = (img.shape[1] // f) * f
    return img[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3)).astype(np.uint8)


def synthesize(image, fs, centre=1900.0, lpm=LPM, start_s=5, phasing_s=30, stop_s=5):
    """Make radiofax audio from an image (rows x WIDTH, 0..255). Used by the tests."""
    period = fs * 60.0 / lpm
    parts = []

    def alt(freq, secs):
        t = np.arange(int(secs * fs)) / fs
        return (np.sign(np.sin(2 * np.pi * freq * t)) > 0).astype(float)

    parts.append(alt(300, start_s))
    n_ph = int(phasing_s * lpm / 60)
    rows = [None] * n_ph + list(image)
    total = int(len(rows) * period)
    pos = (np.arange(total) / period) % 1.0  # fraction of the current line, exact timing
    line_idx = (np.arange(total) / period).astype(int)
    lv = np.empty(total)
    for k, row in enumerate(rows):
        sel = line_idx == k
        if row is None:
            lv[sel] = (pos[sel] < 0.05).astype(float)  # phasing: white pulse, rest black
        else:
            lv[sel] = np.interp(pos[sel] * image.shape[1], np.arange(image.shape[1]), row / 255.0)
    parts.append(lv)
    parts.append(alt(450, stop_s))
    lv = np.concatenate(parts)
    f = centre + (lv * 2 - 1) * DEVIATION
    phase = 2 * np.pi * np.cumsum(f) / fs
    return np.sin(phase) * 0.5
