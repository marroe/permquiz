#!/usr/bin/python3
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROUNDS = 15
STRING_SOURCE_ROUNDS = 10
COMMON_ROUNDS = 10
COMMON_DIGITS = (7, 6, 5, 4, 0)
COMMON_SPECIAL = (4, 2, 1)
SLOT_WEIGHTS = (5, 3, 1)
SCOREBOARD_SIZE = 10
MEDALS = ("\033[1;33m", "\033[1;37m", "\033[38;5;173m")
REVERSE = "\033[7m"
GREEN = "\033[32m"
RED = "\033[31m"
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
HISTORY = Path.home() / ".permquiz_history.json"

FORMATS = {
    "octal": "Octal",
    "binary": "Binary",
    "symbolic": "Unix-permission string",
    "digit": "Special digit (0-7)",
    "slots": "Execute slots (owner group others, e.g. s-T)",
}


# Execute-slot index in rwxrwxrwx -> (letter, special bit): setuid, setgid, sticky.
SPECIAL_SLOTS = {2: ("s", 0o4000), 5: ("s", 0o2000), 8: ("t", 0o1000)}


def render(fmt, bits, special):
    if fmt == "octal":
        return f"{bits:04o}" if special else f"{bits:03o}"
    if fmt == "binary":
        return f"{bits:012b}" if special else f"{bits:09b}"
    if fmt == "digit":
        return str(bits >> 9)
    chars = [c if bits & (1 << (8 - i)) else "-" for i, c in enumerate("rwxrwxrwx")]
    for i, (letter, flag) in SPECIAL_SLOTS.items():
        if bits & flag:
            chars[i] = letter if chars[i] == "x" else letter.upper()
    if fmt == "slots":
        return "".join(chars[i] for i in SPECIAL_SLOTS)
    return "".join(chars)


def parse(fmt, text):
    text = text.strip().replace(" ", "")
    if fmt == "octal":
        if len(text) in (3, 4) and all(c in "01234567" for c in text):
            return int(text, 8)
    elif fmt == "binary":
        if len(text) in (9, 12) and set(text) <= {"0", "1"}:
            return int(text, 2)
    elif fmt == "symbolic":
        if len(text) == 10 and text[0] == "-":
            text = text[1:]
        if len(text) == 9 and set(text) <= set("rwxsStT-"):
            bits = 0
            for i, (c, expected) in enumerate(zip(text, "rwxrwxrwx")):
                bit = 1 << (8 - i)
                if c == expected:
                    bits |= bit
                elif i in SPECIAL_SLOTS and c.lower() == SPECIAL_SLOTS[i][0]:
                    bits |= SPECIAL_SLOTS[i][1] | (bit if c.islower() else 0)
                elif c != "-":
                    return -1  # readable but letters in wrong slots: always a wrong answer
            return bits
    elif fmt == "digit":
        if len(text) == 1 and text in "01234567":
            return int(text)
    elif fmt == "slots":
        if len(text) == 3 and all(c in ("-x" + s + s.upper()) for c, (s, _) in zip(text, SPECIAL_SLOTS.values())):
            return text
        if len(text) == 3 and set(text) <= set("xsStT-"):
            return -1
    return None


def ask(label, fmt, bits, special):
    while True:
        answer = input(f"{label}: ")
        if answer.strip().lower() in ("q", "quit", "exit"):
            raise EOFError
        guess = parse(fmt, answer)
        if guess is None:
            print(f"  Couldn't read that as {label.lower()}, try again.")
            continue
        correct = guess == parse(fmt, render(fmt, bits, special))
        print("  Correct!" if correct else f"  Nope, it's {render(fmt, bits, special)}")
        return correct, answer.strip()


PICK_KEYS = {"o": "octal", "b": "binary", "s": "symbolic"}


def pick_formats():
    """Returns (formats, source); source is None for mixed directions."""
    print("Formats: o=octal, b=binary, s=unix string.")
    print("  Mixed: os, ob, obs ...   One way, shown>answer: s>o, o>s, s>ob ...")
    while True:
        answer = input("Formats [os]: ").strip().lower().replace(" ", "") or "os"
        if answer in ("q", "quit", "exit"):
            raise EOFError
        src, arrow, dst = answer.partition(">")
        if arrow:
            if src in PICK_KEYS and dst and set(dst) <= set(PICK_KEYS) and src not in dst:
                return [PICK_KEYS[src]] + [fmt for key, fmt in PICK_KEYS.items() if key in dst], PICK_KEYS[src]
        elif set(answer) <= set(PICK_KEYS) and len(set(answer)) >= 2:
            return [fmt for key, fmt in PICK_KEYS.items() if key in answer], None
        print("  Try e.g. os (mixed) or s>o (one way).")


def pick_only_source():
    while True:
        answer = input("Shown: m=mixed, s=string (give digit), o=octal (give slots) [m]: ").strip().lower() or "m"
        if answer in ("q", "quit", "exit"):
            raise EOFError
        if answer in ("m", "s", "o"):
            return {"m": None, "s": "symbolic", "o": "octal"}[answer]
        print("  Pick m, s or o.")


def pick_special():
    while True:
        answer = input("Mode: n=normal, s=with special bits, o=special bits only [n]: ").strip().lower() or "n"
        if answer in ("q", "quit", "exit"):
            raise EOFError
        if answer in ("n", "s", "o"):
            return {"n": False, "s": True, "o": "only"}[answer]
        print("  Pick n, s or o.")


def ask_yes_no(prompt):
    while True:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
        if answer in ("q", "quit", "exit"):
            raise EOFError
        if answer in ("", "n", "no"):
            return False
        if answer in ("y", "yes"):
            return True


BASIC_SHEET = """\
r=4  w=2  x=1   one digit each for owner, group, others
0 ---   1 --x   2 -w-   3 -wx   4 r--   5 r-x   6 rw-   7 rwx
binary: one bit per letter, r-x = 101 = 5"""

SPECIAL_SHEET = """\
special digit in front: setuid=4  setgid=2  sticky=1   binary: 3 extra bits in front
in the x slot: owner s, group s, others t; uppercase S/T if no x underneath
rwsr-xr-x 4755   rwxr-sr-x 2755   rwxrwxrwt 1777   rwSr--r-- 4644"""


def build_sheet(special):
    sheets = [BASIC_SHEET, SPECIAL_SHEET] if special else [BASIC_SHEET]
    rule = "─" * max(len(line) for sheet in sheets for line in sheet.splitlines())
    return f"\n{rule}\n".join(sheets) + f"\n{rule}\n"


SPECIAL_INTRO = """\
Special bits are an extra octal digit in front of the normal three:
  setuid = 4   program runs as the file's owner      e.g. /usr/bin/passwd  4755
  setgid = 2   runs as the file's group; in a dir,   e.g. shared folders   2775
               new files inherit the dir's group
  sticky = 1   in a dir, only a file's owner can     e.g. /tmp             1777
               delete or rename it
  Add them up like rwx: 6 = setuid + setgid, 7 = all three.

In the string they take over the execute slot:
  setuid -> owner x slot  is s   rwsr-xr-x  4755
  setgid -> group x slot  is s   rwxr-sr-x  2755
  sticky -> others x slot is t   rwxrwxrwt  1777
  Uppercase when there's no x underneath:   rwSr--r--  4644

String shown: give the special digit.
Octal shown:  give the three execute slots (owner group others), e.g. s-T.
"""


def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def has_uppercase(bits):
    return any(bits & flag and not bits & (1 << (8 - i)) for i, (_, flag) in SPECIAL_SLOTS.items())


def make_permission(common, special, lower):
    extra = random.choice(COMMON_SPECIAL if common else range(8)) if special else 0
    while True:
        bits = extra << 9 | random_base(common)
        if not (lower and has_uppercase(bits)):
            return bits


def random_base(common):
    pool = COMMON_DIGITS if common else range(8)
    digits = sorted((random.choice(pool) for _ in range(3)), reverse=True)
    # Highest digit goes to user/group/other weighted 5:3:1, next highest among the rest.
    slots, weights, perm = [0, 1, 2], list(SLOT_WEIGHTS), [0, 0, 0]
    for digit in digits:
        i = random.choices(range(len(slots)), weights)[0]
        perm[slots.pop(i)] = digit
        weights.pop(i)
    return perm[0] << 6 | perm[1] << 3 | perm[2]


def make_rounds(formats, special, source, lower):
    commons = [True] * COMMON_ROUNDS + [False] * (ROUNDS - COMMON_ROUNDS)
    if source:
        sources = [source] * ROUNDS
    elif "symbolic" in formats:
        others = [f for f in formats if f != "symbolic"]
        sources = ["symbolic"] * STRING_SOURCE_ROUNDS
        sources += [random.choice(others) for _ in range(ROUNDS - STRING_SOURCE_ROUNDS)]
    else:
        sources = [random.choice(formats) for _ in range(ROUNDS)]
    random.shuffle(commons)
    random.shuffle(sources)
    return [(make_permission(c, special, lower), s) for c, s in zip(commons, sources)]


def clear_screen():
    if sys.stdout.isatty():
        print("\033[H\033[2J", end="")


def describe(answers, prefix):
    lines = []
    for shown, label, expected, given, correct in answers:
        verdict = paint("correct", GREEN) if correct else paint(f"wrong, you said {given}", RED)
        lines.append(f"{prefix}{shown:<12} → {label.split(' (')[0]}: {expected}  {verdict}")
    return "\n".join(lines)


def play(formats, special, source, lower, sheet):
    answers, last = [], []
    start = time.monotonic()
    for n, (bits, shown) in enumerate(make_rounds(formats, special, source, lower), 1):
        clear_screen()
        if sheet:
            print(sheet)
        if last:
            print("Last round:\n" + describe(last, "  ") + "\n")
        shown_text = render(shown, bits, special)
        print(f"[{n}/{ROUNDS}]  {shown_text}\n")
        if special == "only":
            asked = ["digit"] if shown == "symbolic" else ["slots"]
        else:
            asked = [f for f in formats if f != shown]
        last = []
        for fmt in asked:
            correct, given = ask(FORMATS[fmt], fmt, bits, special)
            last.append((shown_text, FORMATS[fmt], render(fmt, bits, special), given, correct))
        answers += last
        print()
    return answers, time.monotonic() - start


def ask_name(history):
    last = history[-1].get("name") if history else None
    while True:
        name = input(f"Name [{last}]: " if last else "Name: ").strip() or last
        if name in ("q", "quit", "exit"):
            raise EOFError
        if name:
            return name


def paint(text, code):
    return f"{code}{text}\033[0m" if code and sys.stdout.isatty() else text


def average_time(runs):
    return sum(r["seconds"] for r in runs) / len(runs)


def score(run, average):
    return run["points"] * average / run["seconds"]


def print_scoreboard(runs, board, max_points, current):
    average = average_time(runs)
    runs = sorted(runs, key=lambda r: score(r, average), reverse=True)
    title = "HALL OF FAME  ·  " + board
    header = f" {'#':>2}  {'Name':<12} {'Score':>6}  {'Points':>6}  {'Time':>7}  {'When':<16}"
    width = max(len(header), len(title)) + 2

    print()
    print("╔" + "═" * width + "╗")
    print("║" + title.center(width) + "║")
    print("╠" + "═" * width + "╣")
    print("║" + header.ljust(width) + "║")
    print("╟" + "─" * width + "╢")
    for rank, run in enumerate(runs[:SCOREBOARD_SIZE], 1):
        row = (
            f" {rank:>2}  {run.get('name', '?')[:12]:<12} {score(run, average):>6.1f}  "
            f"{run['points']:>3}/{max_points:<2}  {run['seconds']:>6.1f}s  "
            f"{run['date'][:16].replace('T', ' ')}"
        ).ljust(width)
        code = MEDALS[rank - 1] if rank <= len(MEDALS) else ""
        if run is current:
            code += REVERSE
        print("║" + paint(row, code) + "║")
    print("╚" + "═" * width + "╝")

    rank = runs.index(current) + 1
    if rank > SCOREBOARD_SIZE:
        print(f"  This run placed #{rank} of {len(runs)}.")
    elif rank == 1 and len(runs) > 1:
        print(paint("  NEW HIGH SCORE!", MEDALS[0]))


def setup_and_play(history):
    clear_screen()
    print(f"Permission practice: {ROUNDS} rounds. Type q to quit.\n")
    name = ask_name(history)
    special = pick_special()
    if special == "only":
        formats, source = ["octal", "symbolic"], pick_only_source()
    else:
        formats, source = pick_formats()
    lower = bool(special) and ask_yes_no("Lowercase s/t only (x always set under special bits)?")
    easy = ask_yes_no("Cheat sheet on screen (easy mode)?")
    if special == "only":
        clear_screen()
        print(SPECIAL_INTRO)
        input("Press Enter to start...")
    answers, seconds = play(formats, special, source, lower, build_sheet(special) if easy else None)
    return name, formats, source, special, lower, easy, answers, seconds


def board_info(formats, source, special, lower, easy):
    """Returns (history mode key, board title, max points)."""
    keys = {fmt: key for key, fmt in PICK_KEYS.items()}
    if source:
        dests = [f for f in formats if f != source]
        mode = keys[source] + ">" + "".join(keys[f] for f in dests)
    else:
        mode = "".join(keys[f] for f in formats)

    if special == "only":
        board = "special bits only"
        if source:
            board += "  ·  " + ("string → digit" if source == "symbolic" else "octal → execute slots")
        max_points = ROUNDS
    else:
        if source:
            board = FORMATS[source] + " → " + " + ".join(FORMATS[f] for f in dests)
        else:
            board = " + ".join(FORMATS[f] for f in formats)
        if special:
            board += "  ·  special bits"
        max_points = ROUNDS * (len(formats) - 1)
    if lower:
        board += "  ·  lowercase"
    if easy:
        board += "  ·  easy"
    return mode, board, max_points


def main():
    history = load_history()
    if sys.stdout.isatty():
        print(ALT_SCREEN_ON, end="")
    try:
        game = setup_and_play(history)
    except (EOFError, KeyboardInterrupt):
        game = None
    finally:
        if sys.stdout.isatty():
            print(ALT_SCREEN_OFF, end="")
    if game is None:
        print("Bye!")
        return

    name, formats, source, special, lower, easy, answers, seconds = game
    mode, board, max_points = board_info(formats, source, special, lower, easy)
    current = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "mode": mode,
        "special": special,
        "lower": lower,
        "easy": easy,
        "points": sum(a[4] for a in answers),
        "seconds": round(seconds, 1),
    }
    history.append(current)
    HISTORY.write_text(json.dumps(history, indent=2))

    board_key = (mode, special, lower, easy)
    runs = [
        r for r in history
        if (r["mode"], r.get("special", False), r.get("lower", False), r.get("easy", False)) == board_key
    ]
    average = average_time(runs)
    print("=" * 30)
    print(f"Points: {current['points']}/{max_points}")
    if len(runs) > 1:
        print(f"Time:   {current['seconds']:.1f}s (average {average:.1f}s over {len(runs)} runs)")
    else:
        print(f"Time:   {current['seconds']:.1f}s (first run in this mode, sets the average)")
    print(f"Speed:  x{average / current['seconds']:.2f}")
    print(f"Score:  {score(current, average):.1f}")
    missed = [a for a in answers if not a[4]]
    if missed:
        print("\nMissed:\n" + describe(missed, "  "))
    print_scoreboard(runs, board, max_points, current)


if __name__ == "__main__":
    main()
