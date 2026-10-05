from __future__ import annotations

import ast
import fnmatch
import re
import textwrap
from pathlib import Path


class RepositoryTools:
    """File access constrained to one task workspace."""

    _excluded_dirs = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}
    _secret_names = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials", "secrets.json"}
    _excluded_suffixes = {".pyc", ".sqlite", ".db", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}

    def __init__(self, workspace: str | Path, *, max_file_bytes: int = 256 * 1024, max_results: int = 200,
                 read_window_lines: int = 200):
        self.workspace = Path(workspace).resolve(strict=True)
        self.max_file_bytes = max_file_bytes
        self.read_window_lines = read_window_lines
        self.max_results = max_results

    def for_workspace(self, workspace: str | Path) -> "RepositoryTools":
        return RepositoryTools(workspace, max_file_bytes=self.max_file_bytes, max_results=self.max_results,
                               read_window_lines=self.read_window_lines)

    def list_files(self, path: str = ".") -> dict:
        directory = self._resolve(path)
        if not directory.is_dir():
            raise ValueError("List path must identify a directory.")
        entries = []
        for item in sorted(directory.iterdir(), key=lambda value: value.name):
            if self._excluded(item):
                continue
            entries.append({"path": item.relative_to(self.workspace).as_posix(), "directory": item.is_dir()})
            if len(entries) >= self.max_results:
                break
        return {"entries": entries, "truncated": len(entries) == self.max_results}

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> dict:
        file = self._resolve(path)
        if not file.is_file() or self._excluded(file):
            raise ValueError("Read path must identify an allowed file.")
        if file.stat().st_size > self.max_file_bytes:
            raise ValueError(f"File exceeds the {self.max_file_bytes}-byte read limit.")
        data = file.read_bytes()
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Binary files cannot be read as text.") from error
        lines = content.splitlines(True)
        total = len(lines)
        explicit = start is not None or end is not None
        for value in (start, end):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError("Line numbers must be integers.")
        first = 1 if start is None else start
        last = min(total, first + self.read_window_lines - 1) if end is None else end
        if first < 1 or last < first:
            raise ValueError("Line range must satisfy 1 <= start <= end.")
        last = min(last, total, first + self.read_window_lines - 1)
        truncated = last < total and not (explicit and end is not None and end <= last)
        result = {"path": file.relative_to(self.workspace).as_posix(),
                  "content": "".join(lines[first - 1:last]), "start": first, "end": last,
                  "total_lines": total, "truncated": truncated}
        if truncated:
            result["note"] = (f"Only lines {first}-{last} of {total} are shown; read more with "
                              f'{{"path":"...","start":{last + 1},"end":{min(total, last + self.read_window_lines)}}}.')
        return result

    def search(self, query: str, path: str = ".") -> dict:
        if not isinstance(query, str) or not query or len(query) > 500:
            raise ValueError("Search query must contain 1 to 500 characters.")
        root = self._resolve(path)
        files = [root] if root.is_file() else (item for item in root.rglob("*") if item.is_file())
        matches = []
        for file in files:
            if self._excluded(file):
                continue
            try:
                if file.stat().st_size > self.max_file_bytes:
                    continue
                data = file.read_bytes()
                if b"\x00" in data:
                    continue
                for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
                    if query.casefold() in line.casefold():
                        matches.append({"path": file.relative_to(self.workspace).as_posix(), "line": number, "text": line[:1000]})
                        if len(matches) >= self.max_results:
                            return {"matches": matches, "truncated": True}
            except (OSError, UnicodeDecodeError):
                continue
        return {"matches": matches, "truncated": False}

    def edit_file(self, path: str, content: str) -> dict:
        file = self._resolve(path, allow_missing=True)
        if self._excluded(file) or file.exists() and not file.is_file():
            raise ValueError("Edit path must identify an allowed file.")
        if not isinstance(content, str) or len(content.encode("utf-8")) > self.max_file_bytes:
            raise ValueError(f"File content must be text no larger than {self.max_file_bytes} bytes.")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return {"path": file.relative_to(self.workspace).as_posix(), "bytes_written": len(content.encode("utf-8"))}

    def replace_in_file(self, path: str, old: str, new: str) -> dict:
        file = self._resolve(path)
        if self._excluded(file) or not file.is_file():
            raise ValueError("Edit path must identify an allowed file.")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ValueError("Replace needs non-empty 'old' text and text 'new'.")
        text = self.read_file(path)["content"]
        found = text.count(old)
        if found > 1:
            numbers = [str(text.count("\n", 0, match.start()) + 1) for match in re.finditer(re.escape(old), text)]
            raise ValueError(f"'old' matches {found} times in {path} (lines {', '.join(numbers[:10])}); "
                             "include neighbouring lines so it matches exactly once.")
        if found == 0:
            source_lines = text.splitlines(keepends=True)
            old_lines = textwrap.dedent(old.strip("\r\n")).splitlines()
            matching_starts = []
            for start in range(len(source_lines) - len(old_lines) + 1):
                candidate_text = "".join(source_lines[start:start + len(old_lines)]).rstrip("\r\n")
                candidate = textwrap.dedent(candidate_text).splitlines()
                if candidate == old_lines:
                    matching_starts.append(start)
            if len(matching_starts) == 1:
                start = matching_starts[0]
                end = start + len(old_lines)
                segment = source_lines[start:end]
                indent = segment[0][:len(segment[0]) - len(segment[0].lstrip())]
                newline = "\r\n" if segment[-1].endswith("\r\n") else "\n"
                replacement_lines = textwrap.dedent(new).splitlines()
                ends_with_newline = segment[-1].endswith(("\n", "\r"))
                replacement = [
                    (indent + line if line else "") +
                    (newline if index < len(replacement_lines) - 1 or ends_with_newline else "")
                    for index, line in enumerate(replacement_lines)
                ]
                updated = source_lines[:start] + replacement + source_lines[end:]
                return self.edit_file(path, "".join(updated))
            if len(matching_starts) > 1:
                numbers = [str(sum(line.count("\n") for line in source_lines[:start]) + 1)
                           for start in matching_starts]
                raise ValueError(
                    f"'old' matches after ignoring leading whitespace in {path} "
                    f"(lines {', '.join(numbers[:10])}); include more neighbouring text.")
            near = [str(number) for number, line in enumerate(text.splitlines(), 1)
                    if old.strip().splitlines() and old.strip().splitlines()[0].strip() == line.strip()]
            hint = f" A line with the same text but different whitespace is at line {', '.join(near[:10])}." if near else ""
            raise ValueError(f"'old' was not found in {path}; copy it exactly from a read result.{hint}")
        return self.edit_file(path, text.replace(old, new, 1))

    def insert_after_line(self, path: str, after_line: int, text: str) -> dict:
        file = self._resolve(path)
        if self._excluded(file) or not file.is_file():
            raise ValueError("Edit path must identify an allowed file.")
        if isinstance(after_line, bool) or not isinstance(after_line, int) or not isinstance(text, str) or not text.strip():
            raise ValueError("Insert needs an integer 'after_line' and non-empty text.")
        if file.stat().st_size > self.max_file_bytes:
            raise ValueError(f"File exceeds the {self.max_file_bytes}-byte edit limit.")
        try:
            lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as error:
            raise ValueError("Binary files cannot be edited as text.") from error
        if not 0 <= after_line <= len(lines):
            raise ValueError(f"'after_line' must be between 0 and {len(lines)}; {path} only has {len(lines)} lines.")
        block = text.rstrip("\n").splitlines()
        if after_line and block[0] == block[0].lstrip():
            anchor = lines[after_line - 1]
            indent = anchor[:len(anchor) - len(anchor.lstrip())]
            block = [indent + line if line.strip() else line for line in block]
        if lines and after_line and not lines[after_line - 1].endswith("\n"):
            lines[after_line - 1] += "\n"
        lines[after_line:after_line] = [line + "\n" for line in block]
        return self.edit_file(path, "".join(lines))

    def replace_lines(self, path: str, start_line: int, end_line: int, text: str) -> dict:
        file = self._resolve(path)
        if self._excluded(file) or not file.is_file():
            raise ValueError("Edit path must identify an allowed file.")
        if (isinstance(start_line, bool) or not isinstance(start_line, int)
                or isinstance(end_line, bool) or not isinstance(end_line, int)):
            raise ValueError("'start_line' and 'end_line' must be integers.")
        if not isinstance(text, str):
            raise ValueError("Replacement text must be text.")
        if file.stat().st_size > self.max_file_bytes:
            raise ValueError(f"File exceeds the {self.max_file_bytes}-byte edit limit.")
        try:
            lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as error:
            raise ValueError("Binary files cannot be edited as text.") from error
        total = len(lines)
        if not 1 <= start_line <= end_line <= total:
            raise ValueError(f"Line range must be between 1 and {total} with start_line <= end_line.")
        replacement = text.splitlines(keepends=True)
        if replacement and lines[end_line - 1].endswith(("\n", "\r")) and not text.endswith(("\n", "\r")):
            replacement[-1] += "\n"
        updated = lines[:start_line - 1] + replacement + lines[end_line:]
        return self.edit_file(path, "".join(updated))

    def replace_function(self, path: str, name: str, content: str) -> dict:
        file = self._resolve(path)
        if self._excluded(file) or not file.is_file() or file.suffix != ".py":
            raise ValueError("Function replacement path must identify an allowed Python file.")
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError("Function name must be a Python identifier.")
        if not isinstance(content, str) or len(content.encode("utf-8")) > self.max_file_bytes:
            raise ValueError(f"Replacement function must be text no larger than {self.max_file_bytes} bytes.")
        if file.stat().st_size > self.max_file_bytes:
            raise ValueError(f"File exceeds the {self.max_file_bytes}-byte edit limit.")
        try:
            original = file.read_text(encoding="utf-8")
            tree = ast.parse(original, filename=path)
            replacement_tree = ast.parse(textwrap.dedent(content), filename=path)
        except (UnicodeDecodeError, SyntaxError) as error:
            raise ValueError(f"Python function replacement could not be parsed: {error}") from error
        matches = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one top-level function named {name!r} in {path}; found {len(matches)}.")
        if (len(replacement_tree.body) != 1
                or not isinstance(replacement_tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef))
                or replacement_tree.body[0].name != name
                or replacement_tree.body[0].decorator_list):
            raise ValueError(f"Replacement must contain only an undecorated function named {name!r}.")

        target = matches[0]
        lines = original.splitlines(keepends=True)
        start = target.lineno - 1
        end = target.end_lineno
        indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
        newline = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"
        replacement_lines = textwrap.dedent(content.strip("\r\n")).splitlines()
        ends_with_newline = lines[end - 1].endswith(("\n", "\r"))
        replacement = [
            (indent + line if line else "") +
            (newline if index < len(replacement_lines) - 1 or ends_with_newline else "")
            for index, line in enumerate(replacement_lines)
        ]
        updated = lines[:start] + replacement + lines[end:]
        self.edit_file(path, "".join(updated))
        return {"path": file.relative_to(self.workspace).as_posix(), "function": name}

    def _resolve(self, path: str, *, allow_missing: bool = False) -> Path:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ValueError("Path must be a non-empty workspace-relative path.")
        candidate = Path(path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed.")
        try:
            resolved = (self.workspace / candidate).resolve(strict=not allow_missing)
            resolved.relative_to(self.workspace)
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError("Path escapes the task workspace or does not exist.") from error
        return resolved

    def _excluded(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.workspace)
        except (OSError, RuntimeError, ValueError):
            return True
        relative = path.relative_to(self.workspace)
        if any(part in self._excluded_dirs or part in {".env", ".env.local", ".env.production", ".DS_Store"} for part in relative.parts):
            return True
        name = path.name.casefold()
        if name in self._secret_names or name.startswith(".env."):
            return True
        if path.suffix.casefold() in self._excluded_suffixes:
            return True
        return any(fnmatch.fnmatch(name, pattern) for pattern in ("*.pem", "*.key", "*.token", "*.secret"))
