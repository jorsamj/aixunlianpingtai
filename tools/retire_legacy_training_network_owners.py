from pathlib import Path

APP = Path("static/app.js")

TARGETS = (
    ("window.startTrain=async()=>", 4),
    ("window.startTrain423=async function", 1),
    ("window.submitTrain424=async function", 1),
    ("window.submitTrain425=async function", 2),
    ("window.submitTrain428=async function", 1),
)

MARKER = "/* Classic direct training POST owners retired; TrainingSubmitRuntime owns canonical train-v3 submission. */"
DIRECT_CALL = "api(`/api/v12/projects/${pid()}/train/start`"


def assignment_end(text: str, start: int) -> int:
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"no function body after offset {start}")

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    i = brace
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(text) and text[end] in " \t":
                    end += 1
                if end < len(text) and text[end] == ";":
                    end += 1
                if end < len(text) and text[end] == "\r":
                    end += 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return end
        i += 1
    raise SystemExit(f"unterminated function body after offset {start}")


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    if all(text.count(prefix) == 0 for prefix, _ in TARGETS):
        if DIRECT_CALL in text:
            raise SystemExit("legacy direct /train/start call remains after named owners disappeared")
        print("classic direct training POST owners already retired")
        return

    ranges = []
    for prefix, expected in TARGETS:
        count = text.count(prefix)
        if count != expected:
            raise SystemExit(f"expected {expected} occurrences of {prefix!r}, found {count}")
        cursor = 0
        found = 0
        while True:
            start = text.find(prefix, cursor)
            if start < 0:
                break
            end = assignment_end(text, start)
            ranges.append((start, end, prefix))
            cursor = end
            found += 1
        if found != expected:
            raise SystemExit(f"parser expected {expected} ranges for {prefix!r}, found {found}")

    ranges.sort(key=lambda item: item[0])
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise SystemExit("legacy training owner ranges overlap; refusing migration")

    for start, end, _ in reversed(ranges):
        text = text[:start] + text[end:]

    leftovers = {prefix: text.count(prefix) for prefix, _ in TARGETS if text.count(prefix)}
    if leftovers:
        raise SystemExit(f"legacy named training owners remain: {leftovers}")
    if DIRECT_CALL in text:
        raise SystemExit("direct classic /train/start call remains after migration")

    old_marker = "/* Legacy submitTrain429 implementations retired: TrainingSubmitRuntime is the sole /train/start owner. */"
    text = text.replace(old_marker, MARKER)
    if MARKER not in text:
        text += "\n" + MARKER + "\n"

    APP.write_text(text, encoding="utf-8")
    print(f"retired {len(ranges)} classic direct training POST owners")


if __name__ == "__main__":
    main()
