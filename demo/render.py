"""Render the benchmine narrated demo: real command output + edge-tts narration.

Usage: python demo/render.py   (needs ffmpeg, edge-tts, Pillow, network)
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(ROOT, "demo.mp4")
SDKBIN = "/tmp/bmdemo/bin" + os.pathsep + "/tmp/bmvenv/bin"
SANDBOX = "/tmp/bmdemo"
W, H, FPS = 1280, 720, 24
VOICE = "en-US-AndrewNeural"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, FG = (24, 26, 33), (220, 223, 228)
ANSI = {"31": (255, 95, 95), "32": (95, 215, 120), "33": (240, 200, 80),
        "2": (130, 135, 145), "36": (90, 200, 230), "35": (200, 140, 230), "1": FG}
PROMPT = "dev@laptop textkit $ "

SCENES = [
    {
        "kind": "title",
        "title": "benchmine",
        "sub": "is the new model better on your code?\ndid the old one quietly get worse?",
        "say": "This is bench mine, an open source command line tool that turns your own repository's git history "
               "into a private benchmark for coding agents, so you can compare models on your code, and catch silent quality drops.",
    },
    {
        "kind": "bullets",
        "title": "The problem",
        "bullets": [
            "\"Is Opus 5.5 nerfed?\" 786 pts on HN, Nov 9: vibes vs vibes",
            "MaxxBench: DeepSWE scores collapse on re-check (406 pts)",
            "\"build our own benchmarks based off our own code base\"",
            "Real-SWE benchmarks private code, but someone else's",
            "Nobody has a day-0 baseline on their own work",
        ],
        "say": ("Every week there's a new coding model, and a thread asking if the old one got nerfed. Those threads end in vibes "
                "versus vibes, because nobody has a baseline on their own code. Leaderboards test someone else's tasks."),
    },
    {
        "kind": "term",
        "cmds": ["git log --oneline | head -6", "benchmine mine -v | head -14"],
        "say": ("Here's a small library with a normal history. bench mine mine turns every change that touched code and tests "
                "into a task: the parent commit is the start, the commit or P R message is the prompt, and the change's own tests "
                "are the hidden grader. Docs and version bumps are skipped, and each task must fail before the change and pass after it."),
    },
    {
        "kind": "term",
        "cmds": ["benchmine tasks | head -5", "benchmine tasks 0149"],
        "say": ("Twelve tasks. The agent gets a clean copy of the tree with no git history, so it can't peek at the answer, "
                "and the hidden tests are put back before grading."),
    },
    {
        "kind": "term",
        "cmds": ["benchmine run --agent oracle -j 4 | tail -1", "benchmine run --agent noop -j 4 | tail -1"],
        "say": ("Two built in agents check the benchmark itself. Oracle applies the real change and must score one hundred percent. "
                "No op changes nothing and must score zero."),
    },
    {
        "kind": "term",
        "cmds": ["benchmine run --agent big-model --cmd 'standin big-model' -j 4 | tail -1",
                 "benchmine run --agent small-model --cmd 'standin small-model' -j 4 | tail -1",
                 "benchmine report latest:big-model latest:small-model"],
        "say": ("For this demo the agents are a scripted stand in, not a real model, with made up costs. In your repo you'd point it "
                "at Claude Code, Codex, Aider or any command. The report gives pass rate with a ninety five percent interval, time, "
                "cost per passing task, and diff size next to the real change."),
    },
    {
        "kind": "term",
        "cmds": ["benchmine run --agent big-model --label big-model-nov10 --cmd 'standin big-model-after-update' -j 4 | tail -1",
                 "benchmine compare latest:big-model latest:big-model-nov10; echo exit=$?"],
        "say": ("Weeks later the provider ships an update. Re run the same tasks and compare with your baseline. bench mine pairs "
                "results task by task, runs an exact sign test, and exits with code three on a real drop, so a weekly C I job "
                "can alert you."),
    },
    {
        "kind": "term",
        "cmds": ["cd ~/more-itertools && benchmine mine --limit 60 -j 6 | tail -6",
                 "benchmine run --agent oracle -j 6 | tail -1; benchmine run --agent noop -j 6 | tail -1"],
        "show": ["benchmine mine --limit 60 -j 6 | tail -6",
                 "benchmine run --agent oracle -j 6 | tail -1; benchmine run --agent noop -j 6 | tail -1"],
        "cwd": "mit",
        "say": ("And on a real project. On the last sixty commits of more itertools it finds twenty one valid tasks, from real "
                "bug fixes and features, with the oracle passing all of them and no op passing none."),
    },
    {
        "kind": "term",
        "cmds": ["benchmine agents | head -8", "benchmine run --agent claude-code --model opus --dry-run | tail -5"],
        "say": ("Presets cover the headless modes of Claude Code, Codex, Gemini C L I, Cursor, Aider and Open Code, and dry run shows "
                "exactly what will execute."),
    },
    {
        "kind": "bullets",
        "title": "Limits",
        "bullets": [
            "Demo agents are scripted stand-ins, not models",
            "Presets follow vendor docs; not run in CI (needs paid accounts)",
            "Not a security sandbox: run it in a container or VM",
            "Thin commit messages make thin prompts (use --gh for PR text)",
            "Few tasks = wide intervals; it tells you when there's no signal",
        ],
        "say": ("The limits. Demo agents are scripted, the presets aren't run in C I, and it's not a security sandbox, so use a "
                "container. Thin commit messages make thin prompts, and few tasks mean wide intervals."),
    },
    {
        "kind": "bullets",
        "title": "Try it",
        "bullets": [
            "curl -fsSL https://raw.githubusercontent.com/",
            "   hamarshehmhmd/benchmine/main/install.sh | sh",
            "benchmine mine  ·  benchmine run --agent codex  ·  benchmine compare",
            "github.com/hamarshehmhmd/benchmine",
            "GNU AGPL-3.0-or-later (commercial licenses available)",
        ],
        "say": ("Install it with the one line installer and run bench mine mine in your repo. It's licensed under the GNU Affero "
                "General Public License version 3 or later, with commercial licenses available from the author."),
    },
]


async def tts(text, path):
    import edge_tts
    for attempt in range(8):
        try:
            await edge_tts.Communicate(text, VOICE, rate="+4%").save(path)
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == 7:
                raise
            await asyncio.sleep(5)


def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        text=True,
    )
    return float(out.strip())


EXPORTS = {}


def run_cmd(cmd, cwd):
    if cmd.startswith("export ") and "=" in cmd:
        k, v = cmd[7:].split("=", 1)
        EXPORTS[k] = v
        return ""
    env = dict(os.environ, FORCE_COLOR="1", **EXPORTS)
    env.pop("NO_COLOR", None)
    env["PATH"] = SDKBIN + os.pathsep + env["PATH"]
    env["COLUMNS"] = "120"
    p = subprocess.run(
        ["bash", "-c", "shopt -s nullglob; " + cmd],
        cwd=cwd, capture_output=True, text=True, env=env,
    )
    return (p.stdout + p.stderr).rstrip("\n")


def parse_ansi(line):
    spans, color, bold = [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0":
                    color, bold = FG, False
                elif code == "1":
                    bold = True
                elif code in ANSI:
                    color = ANSI[code]
        elif part:
            spans.append((part, color, bold))
    return spans


class Term:
    def __init__(self):
        self.font = ImageFont.truetype(MONO, 14)
        self.bold = ImageFont.truetype(MONO_B, 14)
        self.cw = self.font.getlength("M")
        self.lh = 20
        self.cols = int((W - 80) / self.cw)

    def wrap(self, spans):
        lines, cur, n = [], [], 0
        for text, c, b in spans:
            while text:
                room = self.cols - n
                if len(text) <= room:
                    cur.append((text, c, b)); n += len(text); text = ""
                else:
                    cut = text.rfind(" ", 0, room + 1)
                    cut = cut if cut > 0 else room
                    cur.append((text[:cut], c, b)); lines.append(cur); cur, n = [], 0
                    text = "    " + text[cut:].lstrip(" ")
        lines.append(cur)
        return lines

    def frame(self, lines, cursor=False):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 14, W - 20, H - 14], 12, fill=(30, 33, 41), outline=(60, 64, 76))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([40 + i * 24, 30, 54 + i * 24, 44], fill=c)
        d.text((W // 2, 37), "~ — bash", font=ImageFont.truetype(SANS, 15), fill=(150, 155, 165), anchor="mm")
        visible = lines[-30:]
        y = 64
        for ln in visible:
            x = 40
            for text, c, b in ln:
                d.text((x, y), text, font=self.bold if b else self.font, fill=c)
                x += self.cw * len(text)
            y += self.lh
        if cursor:
            last = visible[-1] if visible else []
            x = 40 + self.cw * sum(len(t) for t, _, _ in last)
            d.rectangle([x, y - self.lh + 3, x + self.cw - 2, y - 4], fill=FG)
        return img


def card(scene):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if scene["kind"] == "title":
        d.text((W // 2, 280), scene["title"], font=ImageFont.truetype(MONO_B, 78), fill=(95, 215, 120), anchor="mm")
        d.multiline_text((W // 2, 420), scene["sub"], font=ImageFont.truetype(SANS, 32), fill=FG, anchor="mm",
                         align="center", spacing=12)
        d.text((W // 2, 620), "github.com/hamarshehmhmd/benchmine  ·  mine · run · report · compare  ·  GNU AGPL-3.0",
               font=ImageFont.truetype(SANS, 20), fill=(150, 155, 165), anchor="mm")
    else:
        d.text((90, 90), scene["title"], font=ImageFont.truetype(SANS_B, 52), fill=(95, 215, 120))
        f = ImageFont.truetype(SANS, 29)
        y = 200
        for b in scene["bullets"]:
            if b and not b.startswith("   "):
                d.text((90, y), "•", font=f, fill=(240, 200, 80))
            d.text((130, y), b.strip(), font=f, fill=FG)
            y += 58 if b.startswith("   ") or not b else 62
    return img


class Writer:
    def __init__(self, path, audio):
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
             "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-shortest", path],
            stdin=subprocess.PIPE,
        )
        self.n = 0

    def put(self, img, count=1):
        data = img.tobytes()
        for _ in range(count):
            self.p.stdin.write(data)
        self.n += count

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        if self.p.returncode:
            sys.exit("ffmpeg failed")


def _cap_output(out):
    lines = out.splitlines()
    if len(lines) > 26:
        lines = lines[:24] + ["…", lines[-1]]
    return "\n".join(lines)


def render_scene(i, scene, workdir):
    audio = os.path.join(BUILD, f"s{i}.mp3")
    if not os.path.exists(audio):
        asyncio.run(tts(scene["say"], audio))
    total = int((duration(audio) + 0.7) * FPS)
    path = os.path.join(BUILD, f"s{i}.mp4")
    w = Writer(path, audio)
    if scene["kind"] != "term":
        w.put(card(scene), total)
        w.close()
        return path
    t = Term()
    shown = scene.get("show", scene["cmds"])
    wd = os.path.join(SANDBOX, scene["cwd"]) if scene.get("cwd") else workdir
    outputs = [_cap_output(run_cmd(c.replace("cd ~/more-itertools && ", ""), wd)) for c in scene["cmds"]]
    global PROMPT
    PROMPT = "dev@laptop %s $ " % ("more-itertools" if scene.get("cwd") else "textkit")
    # If show has more lines than cmds (a command displayed as several visual lines
    # that map to one executed command), join show into one typed command per output.
    if len(shown) != len(outputs):
        if len(outputs) == 1:
            shown = [" ".join(s.rstrip("\\").strip() for s in shown)]
        elif len(shown) > len(outputs):
            # first N-1 outputs map 1:1; remaining show lines are the last command
            shown = list(shown[: len(outputs) - 1]) + [
                " ".join(s.rstrip("\\").strip() for s in shown[len(outputs) - 1 :])
            ]
    steps = list(zip(shown, outputs))
    typing = sum(len(s) for s, _ in steps) / 32 * FPS
    pause = max(6, int((total - typing) / max(1, len(steps))) - 4)
    lines = []
    for cmd, out in steps:
        prompt = [(PROMPT, (95, 215, 120), True)]
        for k in range(0, len(cmd) + 1, 2):
            frame = t.frame(lines + t.wrap(prompt + [(cmd[:k], FG, False)]), cursor=True)
            w.put(frame)
        lines += t.wrap(prompt + [(cmd, FG, False)])
        for ol in out.splitlines():
            lines += t.wrap(parse_ansi(ol))
        lines.append([])
        hold = min(pause, max(0, total - w.n))
        w.put(t.frame(lines), hold)
    final = t.frame(lines + t.wrap([(PROMPT, (95, 215, 120), True)]), cursor=True)
    if w.n < total:
        w.put(final, total - w.n)
    w.close()
    return path


def main():
    os.makedirs(BUILD, exist_ok=True)
    if os.path.exists(SANDBOX):
        shutil.rmtree(SANDBOX)
    os.makedirs(os.path.join(SANDBOX, "bin"))
    repo = os.path.join(SANDBOX, "textkit")
    subprocess.run([sys.executable, os.path.join(ROOT, "examples", "make_demo_repo.py"), repo], check=True)
    with open(os.path.join(SANDBOX, "bin", "standin"), "w") as fh:
        fh.write('#!/bin/sh\nexec python3 %s "$1" %s.solutions.json\n' % (os.path.join(ROOT, "examples", "agents", "standin.py"), repo))
    os.chmod(os.path.join(SANDBOX, "bin", "standin"), 0o755)
    subprocess.run(["git", "clone", "-q", "https://github.com/more-itertools/more-itertools", os.path.join(SANDBOX, "mit")], check=True)
    subprocess.run(["git", "-C", os.path.join(SANDBOX, "mit"), "checkout", "-q", "f42daddf20"], check=True)
    only = [int(x) for x in sys.argv[1:]]
    parts = [render_scene(i, s, repo) if (not only or i in only) else os.path.join(BUILD, "s%d.mp4" % i)
             for i, s in enumerate(SCENES)]
    with open(os.path.join(BUILD, "list.txt"), "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
         os.path.join(BUILD, "list.txt"), "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", OUT],
        check=True,
    )
    with open(os.path.join(BUILD, "narration.txt"), "w") as fh:
        fh.write("\n\n".join(s["say"] for s in SCENES) + "\n")
    print(OUT, round(duration(OUT), 1), "s")


if __name__ == "__main__":
    main()
