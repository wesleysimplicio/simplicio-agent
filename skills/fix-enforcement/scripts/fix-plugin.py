#!/usr/bin/env python3
"""Fix plugin binary path."""
import os
d = os.path.expanduser("~/.simplicio_agent/plugins/simplicio")
t = os.path.join(d, "tools.py")
with open(t) as f:
    c = f.read()
c = c.replace('return os.environ.get("SIMPLICIO_PATH", "simplicio").strip()', 'return "/Users/wesleysimplicio/.local/bin/simplicio"')
with open(t, "w") as f:
    f.write(c)
i = os.path.join(d, "__init__.py")
with open(i) as f:
    c = f.read()
if "ctx.register_hook" in c:
    c = c.replace('ctx.register_hook("pre_tool_call"', '# DISABLED: ctx.register_hook("pre_tool_call"')
    with open(i, "w") as f:
        f.write(c)
print("FIXED")
