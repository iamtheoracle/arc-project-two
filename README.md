# Arc Project Two

**LLM-Independent Local AI System** — No API keys required. Premium, smart, and sharp.

Runs entirely on your machine using Ollama. Modular plugin architecture for tools and capabilities.

## Features

- **Zero external API keys** — Pure local inference via Ollama
- **Modular Plugin System** — Drop-in plugins with automatic tool discovery
- **Sharp Agent Loop** — Structured reasoning, tool use, and multi-step execution
- **Conversation Memory** — Persistent session context
- **Premium UX** — Clean CLI + optional web interface
- **Extensible** — Easy to add new plugins (Python modules)

## Quick Start

### 1. Install Ollama
```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: download from https://ollama.com
```

### 2. Pull a model
```bash
ollama pull llama3.1:8b
# or: ollama pull qwen2.5:7b / mistral / gemma2
```

### 3. Setup project
```bash
git clone https://github.com/iamtheoracle/arc-project-two.git
cd arc-project-two
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run
```bash
python main.py
```

Or with the web UI:
```bash
python web.py
```

## Plugin System

Plugins live in `plugins/`. Each plugin is a Python file that exports a `PLUGIN` dict or class.

### Example plugin structure
```python
# plugins/calculator.py
PLUGIN = {
    "name": "calculator",
    "description": "Perform precise mathematical calculations",
    "tools": [
        {
            "name": "calculate",
            "description": "Evaluate a math expression safely",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"}
                },
                "required": ["expression"]
            }
        }
    ]
}

def calculate(expression: str) -> str:
    # Safe eval implementation
    ...
```

## Recommended Models

| Model | Size | Strengths | VRAM |
|-------|------|-----------|------|
| llama3.1:8b | 4.7GB | Balanced, good tool use | ~6GB |
| qwen2.5:7b | 4.7GB | Excellent reasoning | ~6GB |
| gemma2:9b | 5.4GB | Sharp, concise | ~7GB |
| mistral:7b | 4.1GB | Fast, solid | ~5GB |

## Architecture

```
arc-project-two/
├── main.py          # CLI agent entrypoint
├── web.py           # Optional Gradio web UI
├── core/
│   ├── agent.py      # Main agent loop
│   ├── llm.py        # Ollama interface
│   ├── plugins.py    # Plugin loader & registry
│   └── memory.py     # Conversation memory
├── plugins/         # Drop-in plugins
│   ├── calculator.py
│   ├── system.py
│   ├── files.py
│   └── ...
└── requirements.txt
```

## License

MIT
