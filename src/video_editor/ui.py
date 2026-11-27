"""Terminal helpers: asking questions, printing tables, reporting progress."""

from __future__ import annotations

import sys
from typing import Callable, Iterable, Sequence


class Abort(RuntimeError):
    """The user pressed Ctrl-C / Ctrl-D, or answered no to a last question."""

# When quiet, every decorative call below becomes a no-op. Errors still go to
# stderr, because something going wrong is never decoration. This is what
# --json uses: the only thing left on stdout is the JSON document itself.
_QUIET = False


def set_quiet(quiet: bool = True) -> None:
    """Silence the decorative output. Questions then refuse rather than hang."""
    global _QUIET
    _QUIET = bool(quiet)


def is_quiet() -> bool:
    return _QUIET



def interactive() -> bool:
    """True only at a real terminal: guards questions we can skip."""
    if _QUIET:
        return False
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def can_ask() -> bool:
    """True when answers can be read at all - a terminal or a pipe.

    Piped input is a legitimate way to drive these steps from a script, so
    questions are allowed; only a closed stdin is hopeless.
    """
    return sys.stdin is not None and not getattr(sys.stdin, "closed", False)


def require_interactive(what: str) -> None:
    if _QUIET:
        raise Abort(
            f"{what} needs an answer, but --json/--quiet mode cannot ask. "
            "Pass the value as a command-line option instead."
        )
    if not can_ask():
        raise Abort(
            f"{what} needs an open input to ask you questions. "
            "Run it from a terminal, or pass the values as command-line options."
        )


# --------------------------------------------------------------------- output
def banner(title: str, subtitle: str = "") -> None:
    if _QUIET:
        return
    line = "=" * max(len(title), 56)
    print(f"\n{line}\n{title}")
    if subtitle:
        print(subtitle)
    print(line)


def heading(text: str) -> None:
    if _QUIET:
        return
    print(f"\n{text}\n{'-' * len(text)}")


def info(text: str) -> None:
    if _QUIET:
        return
    print(text)


def note(text: str) -> None:
    if _QUIET:
        return
    print(f"  . {text}")


def ok(text: str) -> None:
    if _QUIET:
        return
    print(f"  [ok] {text}")


def warn(text: str) -> None:
    # A warning is not decoration, so quiet mode moves it to stderr rather
    # than dropping it: stdout stays a clean JSON document either way.
    if _QUIET:
        print(f"  [!] {text}", file=sys.stderr)
        return
    print(f"  [!] {text}")


def error(text: str) -> None:
    print(f"  [x] {text}", file=sys.stderr)


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Print an aligned text table."""
    if _QUIET:
        return
    rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    if not rows:
        print("  (nothing yet)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print("  " + fmt.format(*headers))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        padded = list(row) + [""] * (len(widths) - len(row))
        print("  " + fmt.format(*padded[: len(widths)]))


def progress(index: int, total: int, label: str) -> None:
    if _QUIET:
        return
    print(f"  [{index}/{total}] {label}", flush=True)


# ---------------------------------------------------------------------- input
def ask(prompt: str, default: str | None = None) -> str:
    """Ask a free-text question."""
    require_interactive("this step")
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Abort("cancelled") from None
    if not answer and default is not None:
        return default
    return answer


def ask_until(
    prompt: str,
    parse: Callable[[str], object],
    default: str | None = None,
) -> object:
    """Ask until `parse` stops raising, so a typo costs one line, not the run."""
    while True:
        raw = ask(prompt, default)
        try:
            return parse(raw)
        except Exception as exc:  # noqa: BLE001 - we show it and ask again
            error(str(exc))


def confirm(prompt: str, default: bool = True) -> bool:
    require_interactive("this step")
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            answer = input(f"{prompt} [{hint}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise Abort("cancelled") from None
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        error("please answer y or n")


def choose(prompt: str, options: Sequence[str], default: str | None = None) -> str:
    """Pick one of a list, by number or by name."""
    require_interactive("this step")
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        marker = " (default)" if option == default else ""
        print(f"  {i}. {option}{marker}")
    while True:
        raw = ask("Choice", default)
        if raw in options:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        error(f"pick 1-{len(options)} or type the name")
