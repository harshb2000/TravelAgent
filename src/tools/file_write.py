import datetime
import re
from pathlib import Path
from tools.base import BaseTool
from models.file_write import FileWriteOutput


def _to_snake_case(subject: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")


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
    description = (
        "Write content to a Markdown file on disk. "
        "Constructs the filename as {subject}_{YYYY-MM-DD}_v1.md using today's date. "
        "If that file already exists, only the version suffix is incremented (v2, v3, …). "
        "Returns the actual path written."
    )
    output_model = FileWriteOutput
    parameters = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Short descriptive slug for the document, e.g. 'tokyo_solo_trip', 'bali_vs_portugal_comparison'. Snake_case, no spaces.",
            },
            "content": {"type": "string", "description": "Full Markdown content to write"},
        },
        "required": ["subject", "content"],
    }

    def execute(self, **kwargs) -> dict:
        subject: str = kwargs["subject"]
        content: str = kwargs["content"]

        try:
            filename = f"{_to_snake_case(subject)}_{datetime.date.today().isoformat()}_v1.md"
            path = _resolve_path(filename)
            path.write_text(content, encoding="utf-8")
            return self._validated_output({"status": "ok", "path": str(path)})
        except OSError as e:
            return {"status": "error", "error": str(e), "fallback": ""}
