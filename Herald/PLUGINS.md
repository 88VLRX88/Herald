# Herald Plugins

Plugins let you add code to Herald without editing `herald_agent/*`.

The main app only knows how to:

- find plugin folders;
- read `plugin.json`;
- import the plugin entrypoint;
- expose declared plugin tools to the agent;
- call one selected plugin function with a small context object.

Everything else lives inside the plugin folder.

## Config

`agent_config.json` enables plugins and points Herald at plugin roots:

```json
"plugins": {
  "enabled": true,
  "directories": ["plugins"],
  "data_directory": ".Herald/plugin-data"
}
```

Herald scans each root for child folders that contain `plugin.json`.

## Plugin Layout

```text
plugins/
  text_tools/
    plugin.json
    plugin.py
    README.md
```

`plugin.json`:

```json
{
  "id": "text_tools",
  "name": "Text Tools",
  "enabled": true,
  "entrypoint": "plugin.py",
  "description": "Small text utility tools.",
  "instructions": "Use text_tools_reverse_text when the user asks to reverse text.",
  "tools": [
    {
      "name": "text_tools_reverse_text",
      "function": "reverse_text",
      "description": "text_tools_reverse_text(text): reverse UTF-8 text."
    }
  ],
  "config": {
    "default_prefix": ""
  }
}
```

`plugin.py`:

```python
def reverse_text(context, text):
    prefix = context.config.get("default_prefix", "")
    return prefix + text[::-1]
```

The plugin does not need to import Herald. Herald passes `context` as the first
argument.

## Context

Plugin functions receive:

- `context.plugin_id`
- `context.workspace`
- `context.plugin_dir`
- `context.data_dir`
- `context.config`
- `context.agent_config`

Path helpers:

- `context.workspace_path("relative/path")`
- `context.plugin_path("relative/path")`
- `context.data_path("relative/path")`

These helpers reject paths that escape their root.

## Tool Calls

A plugin tool can be called by the model like any built-in tool:

```text
TOOL: text_tools_reverse_text {"text": "abc"}
```

Or in JSON protocol:

```json
{"thought":"reverse text","action":{"tool":"text_tools_reverse_text","args":{"text":"abc"}}}
```

Tool names are global. Use a plugin prefix, such as `text_tools_`, to avoid
collisions. Herald rejects plugin tools that duplicate built-in tools or another
plugin tool.

## Runtime Notes

Plugin Python code runs inside the Herald process. Treat plugins as trusted local
code. Put third-party dependencies inside the plugin folder or install them in
the same Python environment that runs Herald.
