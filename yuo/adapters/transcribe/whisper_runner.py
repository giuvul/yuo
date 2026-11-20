"""Transcribe one recording with faster-whisper; run by Yuo in its own Python environment (not Yuo's).

Reads its arguments as JSON on stdin: audio, model, model_dir, lang, prompt, threads, decoder (the path of the
audio decoder Yuo uses), duration (seconds), start (seconds already done, to resume) and window (seconds).
Writes one JSON object per line to stdout: {"duration": s} first, {"language": code} once the first window is heard
(the language given, or the one detected), then {"segment": [start_ms, end_ms, text]} for each stretch of speech and,
after each window, {"done": ms}: everything before it is written out.
Only the standard library, numpy and faster_whisper, so it runs in the environment Yuo installs on demand.

The audio is decoded with ffmpeg (16 kHz mono samples) one window at a time, not with faster-whisper's own
decoder: faster-whisper computes the spectrogram of everything it is given at once, so a whole lecture would
take a gigabyte more memory than a few minutes of it. A window ends before its last stretch of speech when that
runs to the window's edge, and the next window starts there, so no sentence is cut in two.
"""

import json
import subprocess
import sys

EDGE_S = (
    2.0  # a stretch of speech ending this close to a window's edge may be cut: it goes to the next window
)


def main() -> None:
    args = json.loads(sys.stdin.read())
    import numpy as np
    from faster_whisper import WhisperModel  # the on-demand environment's package

    model = WhisperModel(
        args["model"],
        device="cpu",
        compute_type="int8",
        cpu_threads=int(args.get("threads") or 2),
        download_root=args["model_dir"],
    )
    duration = float(args.get("duration") or 0)
    window = float(args.get("window") or 300)
    pos = float(args.get("start") or 0)
    print(json.dumps({"duration": duration}), flush=True)
    told = False
    while duration <= 0 or pos < duration - 0.5:
        raw = subprocess.run(
            [args["decoder"], "-nostdin", "-loglevel", "error", "-ss", f"{pos:.3f}", "-t", f"{window:.3f}",
             "-i", args["audio"], "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            check=True,
            capture_output=True,
        ).stdout  # fmt: skip
        audio = np.frombuffer(raw, dtype=np.float32)
        del raw
        got = len(audio) / 16000
        if got < 0.5:
            break
        last = (duration > 0 and pos + got >= duration - 0.5) or got < window - 0.5
        segments, info = model.transcribe(
            audio,
            language=args.get("lang") or None,
            initial_prompt=args.get("prompt") or None,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
        )
        if not told:
            print(json.dumps({"language": args.get("lang") or info.language}), flush=True)
            told = True
        nxt = pos + got
        for s in segments:
            if not last and s.end > got - EDGE_S and s.start > 1.0:
                nxt = pos + s.start  # unfinished at the edge: the next window starts with it
                break
            print(
                json.dumps({"segment": [int((pos + s.start) * 1000), int((pos + s.end) * 1000), s.text]}),
                flush=True,
            )
        del audio
        pos = nxt
        print(json.dumps({"done": int(pos * 1000)}), flush=True)
        if last:
            break


if __name__ == "__main__":
    main()
