import re
import sys
import zlib
from pathlib import Path


def iter_streams(pdf_bytes: bytes):
    """Yield (header, data) for each stream..endstream occurrence."""
    start = 0
    while True:
        s_idx = pdf_bytes.find(b"stream", start)
        if s_idx == -1:
            return
        # Move to end of 'stream' line (may end with CR or LF)
        line_end = pdf_bytes.find(b"\n", s_idx)
        if line_end == -1:
            return
        data_start = line_end + 1
        e_idx = pdf_bytes.find(b"endstream", data_start)
        if e_idx == -1:
            return
        # crude header backtrack to find '<< ... >>' dictionary before 'stream'
        hdr_start = pdf_bytes.rfind(b"<<", 0, s_idx)
        hdr_end = pdf_bytes.find(b">>", hdr_start, s_idx) if hdr_start != -1 else -1
        header = (
            pdf_bytes[hdr_start : hdr_end + 2]
            if hdr_start != -1 and hdr_end != -1
            else b""
        )
        yield header, pdf_bytes[data_start:e_idx]
        start = e_idx + len(b"endstream")


def try_decompress(data: bytes) -> bytes | None:
    """Attempt to Flate-decompress a PDF stream payload."""
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            continue
    return None


def analyze(pdf_path: Path):
    content = pdf_path.read_bytes()
    rects = []
    strokes = []
    fills_cmyk = []
    strokes_cmyk = []

    # Regex for PDF drawing operators
    re_rect = re.compile(
        rb"([0-9.+-]+)\s+([0-9.+-]+)\s+([0-9.+-]+)\s+([0-9.+-]+)\s+re(?![a-zA-Z])"
    )
    re_line_w = re.compile(rb"([0-9.+-]+)\s+w(?![a-zA-Z])")
    re_fill_k = re.compile(
        rb"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+k(?![a-zA-Z])"
    )
    re_stroke_K = re.compile(
        rb"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+K(?![a-zA-Z])"
    )

    for header, stream_data in iter_streams(content):
        # Only attempt Flate streams
        if b"/FlateDecode" not in header:
            continue
        decompressed = try_decompress(stream_data)
        if not decompressed:
            continue
        # Analyze decompressed operator stream
        for m in re_rect.finditer(decompressed):
            x, y, w, h = (float(m.group(i)) for i in range(1, 5))
            rects.append((x, y, w, h))
        for m in re_line_w.finditer(decompressed):
            strokes.append(float(m.group(1)))
        for m in re_fill_k.finditer(decompressed):
            c, m_, y, k = (float(m.group(i)) for i in range(1, 5))
            fills_cmyk.append((c, m_, y, k))
        for m in re_stroke_K.finditer(decompressed):
            c, m_, y, k = (float(m.group(i)) for i in range(1, 5))
            strokes_cmyk.append((c, m_, y, k))

    # Deduplicate while preserving order
    def dedup(seq):
        seen = set()
        out = []
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    rects_u = dedup(rects)
    strokes_u = dedup(strokes)
    fills_u = dedup(fills_cmyk)
    strokes_cmyk_u = dedup(strokes_cmyk)

    print(f"File: {pdf_path.name}")
    if rects_u:
        # Gather unique widths/heights
        wh = sorted({(round(w, 4), round(h, 4)) for _, _, w, h in rects_u})
        print("  Box sizes (w,h) [pt]:", wh)
        # Heuristic: choose the most common non-page rectangle size
        candidates = [
            (x, y, w, h)
            for (x, y, w, h) in rects
            if 0 < abs(w) < 500 and 0 < abs(h) < 500
        ]
        # Pick a target size as the mode by rounding
        from collections import Counter

        rounded = [(round(abs(w), 3), round(abs(h), 3)) for _, _, w, h in candidates]
        if rounded:
            mode_size, _ = Counter(rounded).most_common(1)[0]
            tx, ty = mode_size
            xs = sorted(
                {
                    round(x, 3)
                    for (x, y, w, h) in candidates
                    if round(abs(w), 3) == tx and round(abs(h), 3) == ty
                }
            )
            ys = sorted(
                {
                    round(y, 3)
                    for (x, y, w, h) in candidates
                    if round(abs(w), 3) == tx and round(abs(h), 3) == ty
                }
            )
            print(f"  Detected inner box size [pt]: {mode_size}")
            print(f"  X positions (unique) [pt]: {xs[:12]} ... total {len(xs)}")
            print(f"  Y positions (unique) [pt]: {ys[:12]} ... total {len(ys)}")
    else:
        print("  Box sizes: none found")
    if strokes_u:
        print("  Stroke widths [pt]:", [round(s, 4) for s in strokes_u])
    else:
        print("  Stroke widths: none found")
    if fills_u:
        print(
            "  Fill CMYK (0..1):", [tuple(round(v, 6) for v in t) for t in fills_u[:10]]
        )
    else:
        print("  Fill CMYK: none found")
    if strokes_cmyk_u:
        print(
            "  Stroke CMYK (0..1):",
            [tuple(round(v, 6) for v in t) for t in strokes_cmyk_u[:10]],
        )
    else:
        print("  Stroke CMYK: none found")


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/analyze_template.py <pdf> [<pdf> ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))


if __name__ == "__main__":
    main()
