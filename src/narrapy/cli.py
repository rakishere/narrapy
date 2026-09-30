#!/usr/bin/env python3
"""
narrapy - Convert a PDF into an audiobook (M4B with chapters, or MP3s)
using fully local text-to-speech: Kokoro or Piper.

Usage examples:
    narrapy book.pdf
    narrapy book.pdf --voice am_michael --speed 1.1
    narrapy book.pdf --engine piper --piper-model voices/en_US-lessac-medium.onnx
    narrapy book.pdf --list-chapters          (preview chapters, no audio)
    narrapy book.pdf --preview                (short voice sample)
    narrapy book.pdf --start-page 5 --end-page 250 --format mp3
    narrapy voices --group best               (listen to voices before choosing)

ffmpeg must be installed and on your PATH, and espeak-ng for Kokoro.

Long books take a while. If the run stops, run the same command again:
finished chapters are kept in the work folder and skipped.
"""

import argparse
import re
import shutil
import subprocess
import sys
import wave
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf
import soundfile as sf

from . import __version__
from .espeak_fix import quiet_espeak_cleanup
from .voices import main as voices_main, voice_list_text


# ---------------------------------------------------------------------------
# 1. Text extraction and cleanup
# ---------------------------------------------------------------------------

def normalize_for_compare(line):
    """Turn a line into a pattern so 'Page 12' and 'Page 13' look identical."""
    return re.sub(r"\d+", "#", line.strip().lower())


def page_blocks(page):
    """Return the text blocks of a page, in reading order, as plain strings."""
    blocks = page.get_text("blocks", sort=True)
    return [b[4].strip() for b in blocks if b[6] == 0 and b[4].strip()]


def find_repeated_edges(doc, first, last):
    """Detect running headers and footers: short blocks that repeat at the top
    or bottom of many pages."""
    counts = Counter()
    pages = 0
    for i in range(first, last + 1):
        blocks = page_blocks(doc[i])
        if not blocks:
            continue
        pages += 1
        edges = set(blocks[:2] + blocks[-2:])
        for b in edges:
            if len(b) < 120:
                counts[normalize_for_compare(b)] += 1
    if pages < 4:
        return set()
    return {text for text, n in counts.items() if n >= max(3, pages * 0.3)}


PAGE_NUMBER = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)


def clean_block(text):
    """Make one block of PDF text speakable."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)        # re-join hyphenated words
    text = text.replace("\n", " ")                       # lines -> one paragraph
    text = re.sub(r"https?://\S+|www\.\S+", "link", text)  # don't read URLs aloud
    text = re.sub(r"\[\d+(,\s*\d+)*\]", "", text)        # citation markers [12]
    text = text.replace("\u00ad", "")                    # soft hyphens
    text = re.sub(r"[\u2013\u2014]", ", ", text)         # long dashes -> pause
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)          # "link ." -> "link."
    return text.strip()


def extract_pages(doc, first, last):
    """Return {page_index: [clean paragraphs]} for the page range."""
    repeated = find_repeated_edges(doc, first, last)
    pages = {}
    for i in range(first, last + 1):
        paragraphs = []
        for block in page_blocks(doc[i]):
            if PAGE_NUMBER.match(block.strip()):
                continue
            if normalize_for_compare(block) in repeated:
                continue
            cleaned = clean_block(block)
            if len(re.sub(r"\W", "", cleaned)) >= 2:
                paragraphs.append(cleaned)
        pages[i] = paragraphs
    return pages


# ---------------------------------------------------------------------------
# 2. Chapter detection
# ---------------------------------------------------------------------------

HEADING = re.compile(
    r"^(chapter|part|section|book)\s+([0-9ivxlcdm]+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)


def chapters_from_toc(doc, first, last):
    """Use the PDF's built-in table of contents (bookmarks), top level only."""
    toc = [t for t in doc.get_toc(simple=True) if t[2] > 0]
    if not toc:
        return []
    top = min(t[0] for t in toc)
    entries = [(title.strip(), page - 1) for lvl, title, page in toc if lvl == top]
    entries = [(t, p) for t, p in entries if first <= p <= last]
    if len(entries) < 2:
        return []
    chapters = []
    if entries[0][1] > first:
        chapters.append(("Opening", first, entries[0][1] - 1))
    for n, (title, start) in enumerate(entries):
        end = entries[n + 1][1] - 1 if n + 1 < len(entries) else last
        if end < start:            # two chapters starting on the same page
            end = start
        chapters.append((title, start, end))
    return chapters


def chapters_from_headings(pages):
    """Fallback: look for short blocks like 'Chapter 3' or 'PART TWO'."""
    starts = []
    for i, paragraphs in pages.items():
        for p in paragraphs[:3]:
            if len(p) < 80 and HEADING.match(p):
                starts.append((p, i))
                break
    if len(starts) < 2:
        return []
    keys = sorted(pages)
    first, last = keys[0], keys[-1]
    chapters = []
    if starts[0][1] > first:
        chapters.append(("Opening", first, starts[0][1] - 1))
    for n, (title, start) in enumerate(starts):
        end = starts[n + 1][1] - 1 if n + 1 < len(starts) else last
        chapters.append((title, start, end))
    return chapters


def chapters_by_page_count(first, last, size):
    """Last resort: fixed-size parts so the player still has navigation."""
    chapters = []
    for n, start in enumerate(range(first, last + 1, size), 1):
        chapters.append((f"Part {n}", start, min(start + size - 1, last)))
    return chapters


def build_chapters(doc, pages, first, last, pages_per_part):
    chapters = chapters_from_toc(doc, first, last)
    source = "PDF table of contents"
    if not chapters:
        chapters = chapters_from_headings(pages)
        source = "chapter headings in the text"
    if not chapters:
        chapters = chapters_by_page_count(first, last, pages_per_part)
        source = f"fixed parts of {pages_per_part} pages"

    result = []
    for title, start, end in chapters:
        text = "\n".join(p for i in range(start, end + 1) for p in pages.get(i, []))
        if text.strip():
            result.append({"title": title, "start": start, "end": end, "text": text})
    return result, source


# ---------------------------------------------------------------------------
# 3. Text-to-speech engines (both run locally)
# ---------------------------------------------------------------------------

class KokoroEngine:
    """Kokoro-82M. Model downloads once from Hugging Face on first run,
    then works offline from the local cache."""

    sample_rate = 24000

    def __init__(self, voice, speed):
        try:
            from kokoro import KPipeline
        except ImportError as e:
            if "Application Control policy" not in str(e):
                raise
            sys.exit("Windows Smart App Control blocked an unsigned spaCy DLL that Kokoro needs.\n"
                     "Fix: pip install \"spacy==3.7.5\" (or turn off Smart App Control, or use WSL).")
        lang = voice[0] if voice and voice[0] in "abefhijpz" else "a"
        self.pipeline = KPipeline(lang_code=lang)
        self.voice = voice
        self.speed = speed
        self.pause = np.zeros(int(self.sample_rate * 0.25), dtype=np.float32)

    def synthesize(self, text, wav_path):
        with sf.SoundFile(wav_path, "w", samplerate=self.sample_rate,
                          channels=1, subtype="PCM_16") as out:
            for result in self.pipeline(text, voice=self.voice, speed=self.speed,
                                        split_pattern=r"\n+"):
                audio = result[2] if isinstance(result, tuple) else result.audio
                if audio is None:
                    continue
                if hasattr(audio, "cpu"):
                    audio = audio.cpu().numpy()
                out.write(np.asarray(audio, dtype=np.float32))
                out.write(self.pause)


class PiperEngine:
    """Piper. Needs a voice file (.onnx) with its .onnx.json next to it."""

    def __init__(self, model_path, speed):
        from piper import PiperVoice
        model = Path(model_path)
        if not model.exists():
            sys.exit(f"Piper voice not found: {model}")
        self.voice = PiperVoice.load(str(model))
        self.length_scale = 1.0 / speed
        self.sample_rate = self.voice.config.sample_rate

    def synthesize(self, text, wav_path):
        with wave.open(str(wav_path), "wb") as wav_file:
            if hasattr(self.voice, "synthesize_wav"):          # piper-tts 1.3+
                from piper import SynthesisConfig
                cfg = SynthesisConfig(length_scale=self.length_scale)
                self.voice.synthesize_wav(text, wav_file, syn_config=cfg)
            else:                                              # piper-tts 1.2
                self.voice.synthesize(text, wav_file, length_scale=self.length_scale,
                                      sentence_silence=0.25)


# ---------------------------------------------------------------------------
# 4. Packaging with ffmpeg
# ---------------------------------------------------------------------------

def ffmeta_escape(value):
    return re.sub(r"([=;#\\\n])", r"\\\1", str(value))


def safe_name(text, limit=60):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    return (text or "untitled")[:limit]


def run_ffmpeg(args):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{result.stderr}")


def build_m4b(chapter_wavs, titles, out_path, work_dir, book_title, author, bitrate):
    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{w.resolve().as_posix()}'\n" for w in chapter_wavs),
        encoding="utf-8")

    lines = [";FFMETADATA1",
             f"title={ffmeta_escape(book_title)}",
             f"album={ffmeta_escape(book_title)}",
             f"artist={ffmeta_escape(author)}",
             "genre=Audiobook", ""]
    position = 0
    for wav, title in zip(chapter_wavs, titles):
        length = int(sf.info(str(wav)).duration * 1000)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={position}", f"END={position + length}",
                  f"title={ffmeta_escape(title)}", ""]
        position += length
    meta_file = work_dir / "chapters.txt"
    meta_file.write_text("\n".join(lines), encoding="utf-8")

    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file),
                "-i", str(meta_file), "-map", "0:a",
                "-map_metadata", "1", "-map_chapters", "1",
                "-c:a", "aac", "-b:a", bitrate, "-ac", "1",
                "-movflags", "+faststart", "-f", "mp4", str(out_path)])
    return position / 1000


def build_mp3s(chapter_wavs, titles, out_dir, book_title, author, bitrate):
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for n, (wav, title) in enumerate(zip(chapter_wavs, titles), 1):
        target = out_dir / f"{n:02d} - {safe_name(title)}.mp3"
        run_ffmpeg(["-i", str(wav), "-c:a", "libmp3lame", "-b:a", bitrate,
                    "-metadata", f"title={title}", "-metadata", f"album={book_title}",
                    "-metadata", f"artist={author}", "-metadata", f"track={n}",
                    "-metadata", "genre=Audiobook", str(target)])
        total += sf.info(str(wav)).duration
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

EXAMPLES = """examples:
  narrapy book.pdf --list-chapters              check the detected chapters
  narrapy book.pdf --dump-text                  review the cleaned text
  narrapy book.pdf --preview --voice bf_emma    1-minute voice sample
  narrapy book.pdf --voice am_michael --speed 1.1 --end-page 212
  narrapy book.pdf --engine piper --piper-model voices/en_US-lessac-medium.onnx

listen to voices before choosing one (plays a ~10 second sample of each):
  narrapy voices --group best                   the 6 best (also: all, american, british, piper)
  narrapy voices af_heart bm_george             only these voices
  narrapy voices --help                         all sample options
"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="narrapy",
        usage="%(prog)s [options] pdf\n       %(prog)s voices [voice options]   (listen to voice samples)",
        description="Convert a PDF into an audiobook with local TTS.\n\n"
                    "To hear the narrator voices, run: narrapy voices  (see: narrapy voices --help)",
        epilog=EXAMPLES + "\n" + voice_list_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdf", help="Path to the PDF file")
    p.add_argument("--engine", choices=["kokoro", "piper"], default="kokoro")
    p.add_argument("--voice", default="af_heart",
                   help="Kokoro voice, e.g. af_heart, af_bella, am_michael, am_fenrir, "
                        "bf_emma, bm_george (default: af_heart)")
    p.add_argument("--piper-model", help="Path to a Piper .onnx voice file")
    p.add_argument("--speed", type=float, default=1.0, help="Reading speed, e.g. 0.9 or 1.15")
    p.add_argument("--format", choices=["m4b", "mp3"], default="m4b")
    p.add_argument("--bitrate", default="64k", help="Audio bitrate (64k is plenty for speech)")
    p.add_argument("--output", help="Output file (m4b) or folder (mp3)")
    p.add_argument("--title", help="Book title (default: PDF metadata or file name)")
    p.add_argument("--author", help="Author (default: PDF metadata)")
    p.add_argument("--start-page", type=int, default=1, help="First page to read (1-based)")
    p.add_argument("--end-page", type=int, help="Last page to read (1-based)")
    p.add_argument("--pages-per-part", type=int, default=15,
                   help="Part size when the PDF has no chapters (default: 15)")
    p.add_argument("--no-announce", action="store_true",
                   help="Don't read the chapter title at the start of each chapter")
    p.add_argument("--list-chapters", action="store_true",
                   help="Show detected chapters and exit (no audio)")
    p.add_argument("--dump-text", action="store_true",
                   help="Save the cleaned text to a .txt file to review, then exit")
    p.add_argument("--preview", action="store_true",
                   help="Make a ~1 minute sample from the first chapter and exit")
    p.add_argument("--keep-work", action="store_true",
                   help="Keep the per-chapter WAV files after finishing")
    p.add_argument("--version", action="version", version=f"narrapy {__version__}")
    return p.parse_args(argv)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "voices":
        return voices_main(argv[1:])
    quiet_espeak_cleanup()
    args = parse_args(argv)
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"File not found: {pdf_path}")
    if shutil.which("ffmpeg") is None and not (args.list_chapters or args.dump_text):
        sys.exit("ffmpeg was not found. Install it and make sure it is on your PATH.")
    if args.engine == "piper" and not args.piper_model:
        sys.exit("--piper-model is required with --engine piper")

    doc = pymupdf.open(str(pdf_path))
    first = max(args.start_page, 1) - 1
    last = min(args.end_page or doc.page_count, doc.page_count) - 1
    meta = doc.metadata or {}
    book_title = args.title or (meta.get("title") or "").strip() or pdf_path.stem
    author = args.author or (meta.get("author") or "").strip() or "Unknown"

    print(f"Reading '{pdf_path.name}' pages {first + 1} to {last + 1}...")
    pages = extract_pages(doc, first, last)
    total_chars = sum(len(p) for ps in pages.values() for p in ps)
    if total_chars < 200:
        sys.exit("Almost no text found. This PDF is probably scanned images and "
                 "needs OCR first (for example with ocrmypdf).")

    chapters, source = build_chapters(doc, pages, first, last, args.pages_per_part)
    print(f"Found {len(chapters)} chapters using {source}.")
    print(f"About {total_chars:,} characters, roughly {total_chars / 900 / 60:.1f} hours of audio.\n")

    if args.list_chapters:
        for n, ch in enumerate(chapters, 1):
            print(f"{n:3d}. {ch['title'][:60]:<60} pages {ch['start'] + 1}-{ch['end'] + 1}"
                  f" ({len(ch['text']):,} chars)")
        return

    if args.dump_text:
        txt_path = pdf_path.with_suffix(".cleaned.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            for ch in chapters:
                f.write(f"===== {ch['title']} =====\n\n{ch['text']}\n\n")
        print(f"Cleaned text saved to {txt_path}")
        return

    if args.engine == "kokoro":
        engine = KokoroEngine(args.voice, args.speed)
    else:
        engine = PiperEngine(args.piper_model, args.speed)

    if args.preview:
        sample = chapters[0]["text"][:1000].rsplit(" ", 1)[0]
        out = pdf_path.with_name(f"{pdf_path.stem}_preview.wav")
        engine.synthesize(sample, out)
        print(f"Preview saved to {out}")
        return

    work_dir = pdf_path.with_name(f"{pdf_path.stem}_audiobook_work")
    work_dir.mkdir(exist_ok=True)

    chapter_wavs, titles = [], []
    for n, ch in enumerate(chapters, 1):
        wav = work_dir / f"{n:03d}.wav"
        titles.append(ch["title"])
        chapter_wavs.append(wav)
        if wav.exists():
            print(f"[{n}/{len(chapters)}] {ch['title'][:50]} (already done, skipping)")
            continue
        print(f"[{n}/{len(chapters)}] {ch['title'][:50]}...", flush=True)
        text = ch["text"] if args.no_announce else f"{ch['title']}.\n{ch['text']}"
        tmp = work_dir / f"{n:03d}.partial.wav"
        engine.synthesize(text, tmp)
        tmp.replace(wav)             # only mark done once the chapter is complete

    print("\nPackaging audiobook...")
    if args.format == "m4b":
        out_path = Path(args.output) if args.output else pdf_path.with_suffix(".m4b")
        seconds = build_m4b(chapter_wavs, titles, out_path, work_dir,
                            book_title, author, args.bitrate)
    else:
        out_path = Path(args.output) if args.output else pdf_path.with_name(
            f"{safe_name(book_title)} - MP3")
        seconds = build_mp3s(chapter_wavs, titles, out_path, book_title, author, args.bitrate)

    if not args.keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)

    h, m = divmod(int(seconds) // 60, 60)
    print(f"Done! {out_path} ({h}h {m}m, {len(chapters)} chapters)")


if __name__ == "__main__":
    main()
