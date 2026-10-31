from __future__ import annotations

import ast
import fnmatch
import re
import textwrap
from pathlib import Path

from .projects import path_matches


_PARSE_ERRORS = (SyntaxError, ValueError, MemoryError, RecursionError)


def split_lines(text: str) -> list[str]:
    """Split on line endings only, keeping them, so line numbers agree with Python's parser."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _newline_of(lines: list[str]) -> str:
    return "\r\n" if lines and lines[0].endswith("\r\n") else "\n"


def _with_newline(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", newline)


class RepositoryTools:
    """File access constrained to one task workspace."""

    _excluded_dirs = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}
    _secret_names = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials", "secrets.json"}
    _excluded_suffixes = {".pyc", ".sqlite", ".db", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}

    def __init__(self, workspace: str | Path, *, max_file_bytes: int = 256 * 1024, max_results: int = 200,
                 read_window_lines: int = 200, allowed_changes: tuple[str, ...] | None = None,
                 history=None):
        self.workspace = Path(workspace).resolve(strict=True)
        self.allowed_changes = allowed_changes
        self.history = history
        self.max_file_bytes = max_file_bytes
        self.read_window_lines = read_window_lines
        self.max_results = max_results

    def for_workspace(self, workspace: str | Path) -> "RepositoryTools":
        return RepositoryTools(workspace, max_file_bytes=self.max_file_bytes, max_results=self.max_results,
                               read_window_lines=self.read_window_lines, allowed_changes=self.allowed_changes,
                               history=self.history)

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
        lines = split_lines(content)
        total = len(lines)
        explicit = start is not None or end is not None
        for value in (start, end):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError("Line numbers must be integers.")
        if total == 0 and not explicit:
            return {"path": file.relative_to(self.workspace).as_posix(), "content": "", "start": 0, "end": 0,
                    "total_lines": 0, "truncated": False}
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
                for number, line in enumerate(split_lines(data.decode("utf-8")), 1):
                    line = line.rstrip("\r\n")
                    if query.casefold() in line.casefold():
                        matches.append({"path": file.relative_to(self.workspace).as_posix(), "line": number, "text": line[:1000]})
                        if len(matches) >= self.max_results:
                            return {"matches": matches, "truncated": True}
            except (OSError, UnicodeDecodeError):
                continue
        return {"matches": matches, "truncated": False}

    def python_files(self) -> list[Path]:
        return sorted(item for item in self.workspace.rglob("*.py")
                      if item.is_file() and not self._excluded(item) and item.stat().st_size <= self.max_file_bytes)

    def _parsed_python_files(self) -> tuple[list[tuple[str, ast.Module]], list[str]]:
        parsed, unparsable = [], []
        for file in self.python_files():
            relative = file.relative_to(self.workspace).as_posix()
            try:
                parsed.append((relative, ast.parse(file.read_bytes(), filename=relative)))
            except (*_PARSE_ERRORS, OSError):
                unparsable.append(relative)
        return parsed, unparsable

    def find_symbol(self, name: str) -> dict:
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError("Symbol name must be a Python identifier.")
        definitions, references = [], []
        parsed, unparsable = self._parsed_python_files()
        for relative, tree in parsed:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    definitions.append({"path": relative, "line": node.lineno, "kind": "function"})
                elif isinstance(node, ast.ClassDef) and node.name == name:
                    definitions.append({"path": relative, "line": node.lineno, "kind": "class"})
                elif isinstance(node, ast.Name) and node.id == name:
                    kind = "variable" if isinstance(node.ctx, ast.Store) else None
                    (definitions.append({"path": relative, "line": node.lineno, "kind": kind}) if kind
                     else references.append({"path": relative, "line": node.lineno}))
                elif isinstance(node, ast.Attribute) and node.attr == name:
                    references.append({"path": relative, "line": node.lineno})
                elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                        (alias.asname or alias.name).split(".")[-1] == name or alias.name == name for alias in node.names):
                    references.append({"path": relative, "line": node.lineno})
        truncated = len(definitions) > self.max_results or len(references) > self.max_results
        return {"definitions": definitions[:self.max_results], "references": references[:self.max_results],
                "unparsable": unparsable[:self.max_results], "truncated": truncated}

    def _module_paths(self) -> dict[str, str]:
        modules = {}
        for file in self.python_files():
            relative = file.relative_to(self.workspace)
            parts = relative.with_suffix("").parts
            parts = parts[:-1] if parts[-1] == "__init__" else parts
            if parts:
                modules[".".join(parts)] = relative.as_posix()
        return modules

    @staticmethod
    def _imported_names(tree: ast.Module, relative: str) -> set[str]:
        package = Path(relative).parent.parts
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    keep = len(package) - (node.level - 1)
                    base = (*package[:max(keep, 0)], *base)
                names.add(".".join(base))
                names.update(".".join((*base, alias.name)) for alias in node.names)
        return names

    def dependencies(self, path: str) -> dict:
        file = self._resolve(path)
        if not file.is_file() or self._excluded(file) or file.suffix != ".py":
            raise ValueError("Dependencies path must identify an allowed Python file.")
        target = file.relative_to(self.workspace).as_posix()
        modules = self._module_paths()
        parsed, unparsable = self._parsed_python_files()
        imports, imported_by = set(), set()
        for relative, tree in parsed:
            resolved = {modules[name] for name in self._imported_names(tree, relative) if name in modules} - {relative}
            if relative == target:
                imports = resolved
            elif target in resolved:
                imported_by.add(relative)
        return {"path": target, "imports": sorted(imports)[:self.max_results],
                "imported_by": sorted(imported_by)[:self.max_results],
                "unparsable": unparsable[:self.max_results]}

    def git_status(self) -> dict:
        if self.history is None:
            raise ValueError("Git state is not available for this task.")
        changes = [{"status": status, "path": path} for status, path in self.history.changes_since_start()]
        return {"changes": changes[:self.max_results], "truncated": len(changes) > self.max_results}

    def git_diff(self) -> dict:
        if self.history is None:
            raise ValueError("Git state is not available for this task.")
        return {"diff": self.history.diff_since_start()}

    def _read_for_edit(self, file: Path) -> str:
        """The whole file, with its line endings intact."""
        if file.stat().st_size > self.max_file_bytes:
            raise ValueError(f"File exceeds the {self.max_file_bytes}-byte edit limit.")
        try:
            return file.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Binary files cannot be edited as text.") from error

    def edit_file(self, path: str, content: str) -> dict:
        file = self._resolve(path, allow_missing=True)
        if self._excluded(file) or file.exists() and not file.is_file():
            raise ValueError("Edit path must identify an allowed file.")
        relative = file.relative_to(self.workspace).as_posix()
        if self.allowed_changes is not None and not path_matches(relative, self.allowed_changes):
            raise ValueError(f"{relative} is outside this task's allowed changes: {', '.join(self.allowed_changes)}.")
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
        text = self._read_for_edit(file)
        found = text.count(old)
        if found > 1:
            numbers = [str(text.count("\n", 0, match.start()) + 1) for match in re.finditer(re.escape(old), text)]
            raise ValueError(f"'old' matches {found} times in {path} (lines {', '.join(numbers[:10])}); "
                             "include neighbouring lines so it matches exactly once.")
        if found == 0:
            source_lines = split_lines(text)
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
                indent = min((line[:len(line) - len(line.lstrip())] for line in segment if line.strip()), key=len)
                newline = "\r\n" if segment[-1].endswith("\r\n") else "\n"
                replacement_lines = textwrap.dedent(new).split("\n")
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
        lines = split_lines(self._read_for_edit(file))
        if not 0 <= after_line <= len(lines):
            raise ValueError(f"'after_line' must be between 0 and {len(lines)}; {path} only has {len(lines)} lines.")
        block = text.rstrip("\n").splitlines()
        top_level_definition = block[0].startswith(("def ", "async def ", "class ", "@"))
        if after_line and block[0] == block[0].lstrip() and not top_level_definition:
            anchor = lines[after_line - 1]
            indent = anchor[:len(anchor) - len(anchor.lstrip())]
            block = [indent + line if line.strip() else line for line in block]
        newline = _newline_of(lines)
        if lines and after_line and not lines[after_line - 1].endswith("\n"):
            lines[after_line - 1] += newline
        lines[after_line:after_line] = [line + newline for line in block]
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
        lines = split_lines(self._read_for_edit(file))
        total = len(lines)
        if not 1 <= start_line <= end_line <= total:
            raise ValueError(f"Line range must be between 1 and {total} with start_line <= end_line.")
        newline = _newline_of(lines)
        replacement = split_lines(_with_newline(text, newline))
        if replacement and lines[end_line - 1].endswith("\n") and not text.endswith("\n"):
            replacement[-1] += newline
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
        original = self._read_for_edit(file)
        try:
            tree = ast.parse(original, filename=path)
            replacement_tree = ast.parse(textwrap.dedent(content), filename=path)
        except _PARSE_ERRORS as error:
            raise ValueError(f"Python function replacement could not be parsed: {type(error).__name__}") from error
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
        lines = split_lines(original)
        start = target.lineno - 1
        end = target.end_lineno
        indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
        newline = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"
        replacement_lines = textwrap.dedent(content.strip("\r\n")).split("\n")
        ends_with_newline = lines[end - 1].endswith("\n")
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
