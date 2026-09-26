#!/usr/bin/env python3
"""
narrapy voices - Make and play a short sample of each voice so you can pick one.

Usage examples:
    narrapy voices                         (all English Kokoro voices + Piper voices)
    narrapy voices af_heart bm_george      (only these voices)
    narrapy voices --group british         (american, british, best, piper)
    narrapy voices --text "Chapter one. It was a bright cold day in April."
    narrapy voices --no-play               (just save the WAV files)
    narrapy voices --list                  (print the voice list and exit)

Samples are saved in ~/.cache/narrapy/voice_samples and reused, so replaying is instant.
"""

import argparse
import hashlib
import sys
from pathlib import Path

SAMPLE_DIR = Path.home() / ".cache" / "narrapy" / "voice_samples"
PIPER_DIR = Path("voices")   # Piper voices are looked up in ./voices of the current folder

KOKORO_VOICES = {
    "American female": ["af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore", "af_sarah",
                        "af_nova", "af_sky", "af_alloy", "af_jessica", "af_river"],
    "American male": ["am_michael", "am_fenrir", "am_puck", "am_echo", "am_eric", "am_liam",
                      "am_onyx", "am_adam", "am_santa"],
    "British female": ["bf_emma", "bf_isabella", "bf_alice", "bf_lily"],
    "British male": ["bm_george", "bm_fable", "bm_lewis", "bm_daniel"],
}
BEST = ["af_heart", "af_bella", "am_michael", "am_fenrir", "bf_emma", "bm_george"]

DEFAULT_TEXT = ("It was a quiet evening when the letter finally arrived. She read it twice, "
                "smiled, and put the kettle on. Some news deserves a cup of tea.")

KOKORO_CACHE = Path.home() / ".cache/huggingface/hub/models--hexgrad--Kokoro-82M/snapshots"


def all_kokoro():
    return [v for group in KOKORO_VOICES.values() for v in group]


def piper_models():
    return sorted(PIPER_DIR.glob("*.onnx"))


def voice_list_text():
    downloaded = {p.stem for p in KOKORO_CACHE.glob("*/voices/*.pt")}
    lines = ["Kokoro voices for --voice (default engine; af_heart is the default voice):"]
    for label, names in KOKORO_VOICES.items():
        shown = [f"{n}*" if n in downloaded else n for n in names]
        lines.append(f"  {label + ':':<19}{', '.join(shown)}")
    lines += [
        f"  Best quality: {', '.join(BEST)}.",
        "  * = already downloaded. Others download once (~0.5 MB) on first use.",
        "  The first letter sets the language (a/b = English); use those for English books.",
        "  Other languages exist (e.g. ef_dora Spanish, ff_siwis French, hf_alpha Hindi,",
        "  if_sara Italian, pf_dora Portuguese); Japanese/Chinese voices need extra packages.",
        "",
        "Piper voices for --piper-model (in ./voices):",
    ]
    models = piper_models()
    lines += [f"  {m.as_posix()}" for m in models] or ["  (none downloaded)"]
    lines += [
        "  Get more: python -m piper.download_voices --download-dir voices <name>",
        "  Browse names at https://huggingface.co/rhasspy/piper-voices",
    ]
    return "\n".join(lines)


def pick_voices(args):
    """Return a list of (name, kind) where kind is 'kokoro' or a Piper model path."""
    piper = {m.stem: m for m in piper_models()}
    if args.voices:
        picked = []
        for v in args.voices:
            if v in piper:
                picked.append((v, piper[v]))
            elif Path(v).suffix == ".onnx" and Path(v).exists():
                picked.append((Path(v).stem, Path(v)))
            elif v in all_kokoro() or (len(v) > 3 and v[2] == "_"):
                picked.append((v, "kokoro"))
            else:
                sys.exit(f"Unknown voice: {v}. Run with --list to see the voices.")
        return picked
    group = args.group
    if group == "american":
        names = KOKORO_VOICES["American female"] + KOKORO_VOICES["American male"]
    elif group == "british":
        names = KOKORO_VOICES["British female"] + KOKORO_VOICES["British male"]
    elif group == "best":
        names = BEST
    elif group == "piper":
        names = []
    else:
        names = all_kokoro()
    picked = [(n, "kokoro") for n in names]
    if group in ("all", "piper"):
        picked += [(m.stem, m) for m in piper_models()]
    return picked


def play(wav_path):
    try:
        import winsound
        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
    except ImportError:
        print("  (playback is only built in on Windows; open the WAV file to listen)")


def main(argv=None):
    try:
        run(argv)
    except KeyboardInterrupt:
        print("\nStopped.")


def run(argv=None):
    p = argparse.ArgumentParser(prog="narrapy voices",
                                description="Make and play a short sample of each voice.")
    p.add_argument("voices", nargs="*",
                   help="Voices to sample, e.g. af_heart bm_george en_US-lessac-medium "
                        "(default: every voice in --group)")
    p.add_argument("--group", choices=["all", "american", "british", "best", "piper"],
                   default="all", help="Which voices to sample when none are named (default: all)")
    p.add_argument("--text", default=DEFAULT_TEXT, help="Sentence to read in each sample")
    p.add_argument("--speed", type=float, default=1.0, help="Reading speed, e.g. 0.9 or 1.15")
    p.add_argument("--no-play", action="store_true", help="Only save the samples, don't play them")
    p.add_argument("--regenerate", action="store_true", help="Remake samples even if saved ones exist")
    p.add_argument("--list", action="store_true", help="Print the available voices and exit")
    args = p.parse_args(argv)

    if args.list:
        print(voice_list_text())
        return

    picked = pick_voices(args)
    if not picked:
        sys.exit("No voices to sample.")

    # Import the engines only when needed; they pull in torch and friends.
    from .cli import KokoroEngine, PiperEngine
    from .espeak_fix import quiet_espeak_cleanup
    quiet_espeak_cleanup()

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # Different text or speed gets its own files, so saved samples always match.
    tag = hashlib.sha1(f"{args.text}|{args.speed}".encode()).hexdigest()[:8]
    kokoro_by_lang = {}   # one Kokoro pipeline per language, voice switched per sample

    print(f"Sampling {len(picked)} voice(s). Press Ctrl+C to stop.\n")
    for i, (name, kind) in enumerate(picked, 1):
        wav = SAMPLE_DIR / f"{name}_{tag}.wav"
        if args.regenerate or not wav.exists():
            if kind == "kokoro":
                lang = name[0]
                if lang not in kokoro_by_lang:
                    kokoro_by_lang[lang] = KokoroEngine(name, args.speed)
                engine = kokoro_by_lang[lang]
                engine.voice = name
            else:
                engine = PiperEngine(kind, args.speed)
            tmp = wav.with_suffix(".partial.wav")
            engine.synthesize(args.text, tmp)
            tmp.replace(wav)
        label = "Piper" if kind != "kokoro" else "Kokoro"
        print(f"[{i}/{len(picked)}] {name} ({label})", flush=True)
        if not args.no_play:
            play(wav)

    print(f"\nSamples saved in {SAMPLE_DIR}")
    print('Use one with: narrapy "book.pdf" --voice <name>')
    print('  (Piper:     narrapy "book.pdf" --engine piper --piper-model voices/<name>.onnx)')
