import re
from pathlib import Path
from tools.base import BaseTool
from models.file_write import FileWriteOutput


def _resolve_path(filename: str) -> Path:
    """Return a non-colliding path, incrementing _vN suffix if needed."""
    path = Path(filename)
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix

    # Extract existing version number if present, e.g. "report_v1" → ("report_", 1)
    m = re.match(r"^(.*_v)(\d+)$", stem)
    if m:
        base, n = m.group(1), int(m.group(2))
    else:
        base, n = stem + "_v", 1

    while True:
        n += 1
        candidate = Path(f"{base}{n}{suffix}")
        if not candidate.exists():
            return candidate


class FileWriteTool(BaseTool):
    name = "file_write"
    description = "Write content to a Markdown file on disk. Use for saving itineraries, comparisons, and trip summaries."
    output_model = FileWriteOutput
    parameters = {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Desired filename, e.g. 'itinerary_tokyo_2026-06-20_v1.md'"},
            "content": {"type": "string", "description": "Full Markdown content to write"},
        },
        "required": ["filename", "content"],
    }

    def execute(self, **kwargs) -> dict:
        filename: str = kwargs["filename"]
        content: str = kwargs["content"]

        try:
            path = _resolve_path(filename)
            path.write_text(content, encoding="utf-8")
            return self._validated_output({"status": "ok", "path": str(path)})
        except OSError as e:
            return {"status": "error", "error": str(e), "fallback": ""}
