from pathlib import Path


APP = Path("static/app.js")
NEEDLE = "window.submitTrain429=async function"
MARKER = "/* Legacy submitTrain429 implementations retired: TrainingSubmitRuntime is the sole /train/start owner. */"
EXPECTED = 3


def function_assignment_end(text: str, start: int) -> int:
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit("submitTrain429 assignment has no function body")

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
    raise SystemExit("unterminated submitTrain429 function body")


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    count = text.count(NEEDLE)
    if count == 0 and text.count(MARKER) == 1:
        print("legacy submitTrain429 implementations already retired")
        return
    if count != EXPECTED:
        raise SystemExit(f"expected {EXPECTED} legacy submitTrain429 implementations, found {count}")
    if MARKER in text:
        raise SystemExit("retirement marker exists while legacy submit implementations remain")

    ranges = []
    cursor = 0
    while True:
        start = text.find(NEEDLE, cursor)
        if start < 0:
            break
        ranges.append((start, function_assignment_end(text, start)))
        cursor = ranges[-1][1]

    if len(ranges) != EXPECTED:
        raise SystemExit(f"parser expected {EXPECTED} ranges, found {len(ranges)}")

    for start, end in reversed(ranges):
        text = text[:start] + text[end:]

    if NEEDLE in text:
        raise SystemExit("legacy submitTrain429 implementation remains after migration")

    insertion = text.find("/* ============================================================", ranges[0][0] if ranges else 0)
    if insertion < 0:
        insertion = ranges[0][0]
    text = text[:insertion] + MARKER + "\n" + text[insertion:]
    APP.write_text(text, encoding="utf-8")
    print(f"retired {EXPECTED} legacy submitTrain429 implementations")


if __name__ == "__main__":
    main()
