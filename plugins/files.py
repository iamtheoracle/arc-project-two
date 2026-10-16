"""Safe file operations plugin."""
from pathlib import Path

PLUGIN = {
    "name": "files",
    "description": "Read local files (read-only for safety)",
    "tools": [
        {
            "name": "read_file",
            "description": "Read the contents of a local text file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to the file"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return", "default": 8000}
                },
                "required": ["path"]
            }
        }
    ]
}

def read_file(path: str, max_chars: int = 8000) -> str:
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + "\n... [truncated]"
        return f"Contents of {p}:\n\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"
