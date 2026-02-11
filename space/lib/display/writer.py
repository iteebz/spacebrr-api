import json
import sys
from typing import Any, Protocol


class Writer(Protocol):
    def print(self, text: str = "") -> None: ...

    def error(self, text: str) -> None: ...

    def json(self, data: Any) -> None: ...


class StdWriter:
    def print(self, text: str = "") -> None:
        sys.stdout.write(text + "\n")

    def error(self, text: str) -> None:
        sys.stderr.write(text + "\n")

    def json(self, data: Any) -> None:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")


class TestWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.json_outputs: list[Any] = []

    def print(self, text: str = "") -> None:
        self.lines.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def json(self, data: Any) -> None:
        self.json_outputs.append(data)


def std() -> Writer:
    return StdWriter()


def test() -> TestWriter:
    return TestWriter()
