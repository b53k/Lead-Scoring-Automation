import re
from typing import Optional 

def slice_section(md: str, heading: str) -> Optional[str]:
    """Return the body under a markdown heading, up to the next same-or-higher heading."""

    m = re.search(
        rf"(?im)^(#{{1,6}})\s+{re.escape(heading)}\s*$",
        md,
    )
    if not m:
        return None
    
    level = len(m.group(1))
    start = m.end()
    nxt = re.search(rf"(?m)^#{{1,{level}}}\s+\S", md[start:])
    end = start + nxt.start() if nxt else len(md)

    return md[start:end].strip()


def slice_around(md: str, anchor: str, before: int = 0, after: int = 20) -> Optional[str]:
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if anchor.lower() in line.lower():
            return "\n".join(lines[max(0, i - before): i + after + 1])
    return None
