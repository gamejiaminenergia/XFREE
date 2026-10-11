"""Record the session from its own frame buffer: no X, no window, no capture.

The engine already hands out raw RGB (320x200x3), so a video can be produced
exactly, frame by frame, at the engine's own rate.  That beats grabbing the
screen: nothing else of the desktop leaks into the clip, no zoom or crop is
guessed, and the frame count is the tick count.

    uv run --no-sync python tools/record_headless.py --seconds 20 --out clip.mp4
    uv run --no-sync python tools/record_headless.py --seconds 20 --fake --out demo.mp4

With ``--fake`` it answers with a local deterministic model: no key, no cost.
Prints a JSON summary on stdout so a wrapper can write the sidecar.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("JEV_NO_LOG", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_duum.controller import JevDuumController  # noqa: E402
from jev_duum.integration import DuumRuntime, default_duum_checkout, load_duum  # noqa: E402
from jev_duum.session.core import Session  # noqa: E402
from jev_duum.wad import default_wad_path, resolve_wad  # noqa: E402

FPS = 60


class FakeClient:
    """A local, deterministic model: the tool must work with no key and no cost."""

    endpoint = "fake://local"
    logger = None
    model = "fake-local"

    ANSWERS = {
        "movement": {
            "type": "choice", "choice": "strafe_left", "confidence": 0.6,
            "probabilities": {
                "forward": 0.10, "forward_left": 0.02, "forward_right": 0.02,
                "strafe_left": 0.60, "strafe_right": 0.08, "back_left": 0.01,
                "back_right": 0.01, "back": 0.06, "hold": 0.10,
            },
        },
        "aim": {
            "type": "choice", "choice": "right", "confidence": 0.7,
            "probabilities": {"left": 0.1, "straight": 0.2, "right": 0.7},
        },
        "interaction": {
            "type": "choice", "choice": "fire", "confidence": 0.8,
            "probabilities": {"fire": 0.8, "use": 0.1, "neither": 0.1},
        },
        "target": {
            "type": "choice", "choice": "advance", "confidence": 0.5,
            "probabilities": {
                "target_1": 0.2, "target_2": 0.2, "target_3": 0.1,
                "exit": 0.2, "advance": 0.3,
            },
        },
    }

    def __init__(self, tokens: int = 1180):
        self.tokens = tokens
        self.calls = 0

    def ask(self, state, questions, *, model=None, context=None):
        self.calls += 1
        return {
            "model": self.model,
            "answers": {name: self.ANSWERS[name] for name in questions},
            "usage": {"input_tokens": self.tokens, "output_tokens": 44},
        }


def nvenc_works() -> bool:
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "nullsrc=s=320x240:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
        capture_output=True, check=False,
    )
    return probe.returncode == 0


def encoder_args(name: str, crf: int) -> tuple[str, list[str]]:
    if name == "auto":
        name = "nvenc" if nvenc_works() else "x264"
    if name == "x264":
        return "libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    codec = "hevc_nvenc" if name == "hevc" else "h264_nvenc"
    args = ["-c:v", codec, "-preset", "p5", "-tune", "hq", "-rc", "vbr",
            "-cq", str(crf), "-b:v", "0"]
    if codec == "hevc_nvenc":
        args += ["-tag:v", "hvc1"]
    return codec, args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="record_headless", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=20.0,
                        help="simulated seconds to record (0 = until the episode ends)")
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument("--encoder", default="auto", choices=("auto", "x264", "nvenc", "hevc"))
    parser.add_argument("--duum-path", type=Path, default=default_duum_checkout())
    parser.add_argument("--wad", type=Path, default=default_wad_path())
    parser.add_argument("--map", dest="map_name", default="E1M1")
    parser.add_argument("--pilot", default="jev-assisted", choices=("jev", "jev-assisted"))
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--decision-rate", type=float, default=10.0)
    parser.add_argument("--size", default="320x200")
    parser.add_argument("--fake", action="store_true",
                        help="local deterministic model instead of calling Jev (0 $)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    width, height = (int(part) for part in args.size.lower().split("x"))
    wad = resolve_wad(args.wad)
    if args.fake:
        controller = JevDuumController(
            client=FakeClient(), assisted=args.pilot == "jev-assisted",
            prompt_version=args.prompt_version, pilot=args.pilot,
        )
    else:
        controller = JevDuumController(
            assisted=args.pilot == "jev-assisted",
            prompt_version=args.prompt_version, pilot=args.pilot,
        )
    modules = load_duum(args.duum_path, frontend=False)
    codec, encode = encoder_args(args.encoder, args.crf)

    runtime = DuumRuntime(modules, wad.path, args.map_name, width, height)
    session = Session(runtime, controller, decision_rate=args.decision_rate,
                      pixels=True, frame_every=1, pilot=args.pilot)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
         "-r", str(args.fps), "-i", "-",
         *encode, "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
         str(args.out)],
        stdin=subprocess.PIPE,
    )
    budget = int(args.seconds * args.fps) if args.seconds > 0 else 0
    frames = 0
    interrupted = False
    try:
        while True:
            frame = session.step()
            if frame.rgb is not None:
                ffmpeg.stdin.write(frame.rgb)
                frames += 1
            if budget and frames >= budget:
                break
            if not budget and (frame.dead or frame.finished):
                break
    except KeyboardInterrupt:
        # Ctrl-C is a normal way to stop: the finally still closes the MP4.
        interrupted = True
    finally:
        ffmpeg.stdin.close()
        code = ffmpeg.wait()
        summary = session.summary()
        session.close()

    if code != 0:
        print(f"ffmpeg fell over with status {code}", file=sys.stderr)
        return 1
    print(json.dumps({
        "out": str(args.out),
        "encoder": codec,
        "width": width,
        "height": height,
        "fps": args.fps,
        "frames": frames,
        "seconds": round(frames / args.fps, 2),
        "interrupted": interrupted,
        "pilot": args.pilot,
        "model": controller.model if not args.fake else "fake-local",
        "prompt_version": controller.prompt_version,
        "applied_decisions": summary["applied_decisions"],
        "kills": summary["kills"],
        "engine_commit": modules.commit,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
