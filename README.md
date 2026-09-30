# Narrapy

Turn any text-based PDF into an audiobook on your own computer. Narrapy reads the PDF, cleans up the text, detects chapters, narrates each chapter with a local neural voice ([Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) or [Piper](https://github.com/rhasspy/piper)), and packages everything into a single `.m4b` audiobook with chapter markers, title, and author.

No cloud services, no API keys. After the first run it works fully offline.

## Features

- **Chapters, automatically.** Uses the PDF's built-in table of contents first. If there isn't one, it looks for "Chapter 3" or "Part Two" style headings. As a last resort it splits the book into 15-page parts so you can still skip around.
- **Clean narration.** Removes running headers and footers, page numbers, and citation markers like `[12]`. Rejoins hyphenated words and replaces URLs with the word "link" so they aren't read out letter by letter.
- **Resumable.** A long book can take hours on CPU. If a run stops, run the same command again and finished chapters are skipped.
- **Voice sampler.** Listen to a short sample of every voice before choosing one.
- **Two engines.** Kokoro (default, higher quality) or Piper (faster, lighter).
- **M4B or MP3.** One `.m4b` with chapters for audiobook players, or one MP3 per chapter.

## Requirements

- Python 3.10, 3.11, or 3.12 (Kokoro doesn't support 3.13+ yet)
- [ffmpeg](https://ffmpeg.org/) on your PATH
- [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases) (Kokoro uses it for unusual words)
- A PDF with a real text layer. Scanned PDFs need OCR first, for example with [ocrmypdf](https://github.com/ocrmypdf/OCRmyPDF).

Installing pulls in PyTorch for Kokoro, so expect a download of several hundred MB. On the first Kokoro run the voice model (about 330 MB) downloads once from Hugging Face.

## Install

Install the tools first:

```powershell
# Windows
winget install Gyan.FFmpeg
winget install eSpeak-NG.eSpeak-NG
# then open a new terminal so ffmpeg is on your PATH
```

On macOS use `brew install ffmpeg espeak-ng`; on Debian/Ubuntu use `sudo apt install ffmpeg espeak-ng`.

Then install Narrapy into a Python 3.10-3.12 virtual environment:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install narrapy
```

### From source

```bash
git clone https://github.com/rakishere/narrapy.git
cd narrapy
python -m venv .venv
pip install -e .
```

On Windows, `run.ps1` runs Narrapy with the project's `.venv` without activating it, e.g. `.\run.ps1 "book.pdf" --preview`.

## Usage

```bash
narrapy --help                                     # all options and the list of voices
narrapy "book.pdf" --list-chapters                 # check the chapters look right
narrapy "book.pdf" --dump-text                     # review the cleaned text
narrapy "book.pdf" --preview --voice am_michael    # 1-minute voice sample from the book
narrapy "book.pdf" --voice am_michael --speed 1.1  # make the audiobook
```

The result is saved next to the PDF as `book.m4b`.

Skip front or back matter (preface, notes, index) with `--start-page` and `--end-page`:

```bash
narrapy "book.pdf" --voice bf_emma --start-page 9 --end-page 212
```

Use Piper instead of Kokoro (download a voice into `./voices` first):

```bash
python -m piper.download_voices --download-dir voices en_US-lessac-medium
narrapy "book.pdf" --engine piper --piper-model voices/en_US-lessac-medium.onnx
```

### Choosing a voice

Play a short sample of each voice (Ctrl+C stops):

```bash
narrapy voices --group best             # the 6 best voices
narrapy voices                          # all English Kokoro voices + Piper voices in ./voices
narrapy voices --group british          # also: american, piper
narrapy voices am_michael bm_george     # only these voices
narrapy voices --text "Your own sentence" --speed 1.1
```

Samples are saved in `~/.cache/narrapy/voice_samples` and reused, so replaying is instant. Playback is built in on Windows; on other systems the WAV files are saved for you to open.

| Group | Kokoro voices |
|---|---|
| American female | af_heart (default), af_bella, af_nicole, af_aoede, af_kore, af_sarah, af_nova, af_sky, af_alloy, af_jessica, af_river |
| American male | am_michael, am_fenrir, am_puck, am_echo, am_eric, am_liam, am_onyx, am_adam, am_santa |
| British female | bf_emma, bf_isabella, bf_alice, bf_lily |
| British male | bm_george, bm_fable, bm_lewis, bm_daniel |

Good starting points: af_heart, af_bella, am_michael, am_fenrir, bf_emma, bm_george.

### All options

| Option | Description |
|---|---|
| `--engine {kokoro,piper}` | Text-to-speech engine (default: kokoro) |
| `--voice VOICE` | Kokoro voice (default: af_heart) |
| `--piper-model PATH` | Piper `.onnx` voice file (required with `--engine piper`) |
| `--speed SPEED` | Reading speed, e.g. 0.9 or 1.15 |
| `--format {m4b,mp3}` | One `.m4b` with chapters, or one MP3 per chapter |
| `--bitrate BITRATE` | Audio bitrate (default: 64k, plenty for speech) |
| `--output PATH` | Output file (m4b) or folder (mp3) |
| `--title`, `--author` | Override the PDF metadata |
| `--start-page`, `--end-page` | Page range to read (1-based) |
| `--pages-per-part N` | Part size when the PDF has no chapters (default: 15) |
| `--no-announce` | Don't read the chapter title at the start of each chapter |
| `--list-chapters` | Show detected chapters and exit |
| `--dump-text` | Save the cleaned text to `book.cleaned.txt` and exit |
| `--preview` | Make a ~1 minute sample from the first chapter and exit |
| `--keep-work` | Keep the per-chapter WAV files after finishing |
| `--version` | Show the version |

## How long does it take?

Kokoro runs on the CPU. On a 10-core laptop it produces about 1.5 minutes of audio per minute, so a 285-page book (about 8.5 hours of audio) takes roughly 6 hours. Piper is several times faster. Runs are resumable, so you can stop and continue later - just keep the same `--voice` and `--speed`.

## Troubleshooting

- **`No module named 'soundfile'` (or similar)** - you ran the system Python. Activate the virtual environment first, or use `run.ps1` from a source checkout.
- **"An Application Control policy has blocked this file"** - Windows Smart App Control blocked a new, unsigned spaCy DLL. Install an older build: `pip install "spacy==3.7.5"`. Narrapy prints this fix when it detects the block. To see the narrator voices, run `narrapy voices`.
- **"No module named pip" on the first Kokoro run** - Kokoro downloads the spaCy English model with pip. Environments made by `uv venv` have no pip; run `python -m ensurepip` or `uv pip install pip`, then retry.
- **"Cleanup: removed ... espeak-ng.dll temp folder(s)"** - harmless and Windows-only. Kokoro's phonemizer copies espeak-ng.dll to a temp folder and can't delete it at exit while it is still loaded, so Narrapy removes those folders on the next run.
- **"Almost no text found"** - the PDF is scanned images. Run OCR on it first.

## Project layout

| File | Purpose |
|---|---|
| `src/narrapy/cli.py` | The converter: text extraction, cleanup, chapters, TTS, packaging |
| `src/narrapy/voices.py` | `narrapy voices`: make and play short samples of each voice |
| `src/narrapy/espeak_fix.py` | Quiets a harmless Windows espeak-ng cleanup error |
| `run.ps1` | Windows launcher for a source checkout |

## License

MIT. Kokoro-82M is Apache 2.0; Piper voices have their own licenses listed on their model pages. Only convert books you have the right to use.
