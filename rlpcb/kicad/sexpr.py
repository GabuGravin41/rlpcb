"""Lossless-enough S-expression parser/writer for KiCad files.

KiCad files (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod, .kicad_dru ...) are
S-expressions. We parse into a tree of :class:`Node` objects. Atoms are kept as
Python ``str``; quoted atoms are :class:`QStr` so the writer can re-quote them.
Every node records its character span in the source text, which lets editors
splice new content into a user's file without re-serialising (and possibly
disturbing) the rest of it.
"""
from __future__ import annotations

import re
from typing import Iterator, List, Optional, Union


class QStr(str):
    """A string atom that was quoted in the source (or must be quoted on output)."""
    __slots__ = ()


Atom = Union[str, QStr]


class Node:
    __slots__ = ("items", "start", "end")

    def __init__(self, items: Optional[list] = None, start: int = -1, end: int = -1):
        self.items: list = items if items is not None else []
        self.start = start
        self.end = end

    # ------------------------------------------------------------------ access
    @property
    def head(self) -> str:
        return self.items[0] if self.items and isinstance(self.items[0], str) else ""

    @property
    def args(self) -> list:
        return self.items[1:]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def __iter__(self):
        return iter(self.items)

    def children(self, head: Optional[str] = None) -> Iterator["Node"]:
        for it in self.items:
            if isinstance(it, Node) and (head is None or it.head == head):
                yield it

    def child(self, head: str) -> Optional["Node"]:
        for it in self.items:
            if isinstance(it, Node) and it.head == head:
                return it
        return None

    def atoms(self) -> List[str]:
        return [a for a in self.items[1:] if not isinstance(a, Node)]

    def value(self, head: str, default=None, idx: int = 1):
        """Return atom ``idx`` of the first child with ``head`` (e.g. (at 1 2) -> '1')."""
        c = self.child(head)
        if c is None or len(c.items) <= idx:
            return default
        v = c.items[idx]
        return v if not isinstance(v, Node) else default

    def fvalue(self, head: str, default: float = 0.0, idx: int = 1) -> float:
        v = self.value(head, None, idx)
        try:
            return float(v) if v is not None else default
        except ValueError:
            return default

    def xy(self, head: str = "at"):
        c = self.child(head)
        if c is None:
            return None
        nums = [float(a) for a in c.items[1:] if not isinstance(a, Node) and _is_num(a)]
        return nums

    def has_flag(self, flag: str) -> bool:
        """True for bare atom flags (KiCad<=7 'hide') and (flag yes) (KiCad 8+)."""
        for it in self.items[1:]:
            if isinstance(it, Node):
                if it.head == flag:
                    return len(it.items) < 2 or it.items[1] in ("yes", "true")
            elif it == flag and not isinstance(it, QStr):
                return True
        return False

    def find_all(self, head: str) -> Iterator["Node"]:
        """Depth-first search for all descendant nodes with ``head``."""
        stack = [self]
        while stack:
            n = stack.pop()
            for it in reversed(n.items):
                if isinstance(it, Node):
                    if it.head == head:
                        yield it
                    stack.append(it)

    # ------------------------------------------------------------- mutation
    def set_value(self, head: str, *vals):
        c = self.child(head)
        new = [head, *vals]
        if c is None:
            self.items.append(Node(new))
        else:
            c.items = new

    def __repr__(self):
        return f"Node({dump(self, compact=True)[:120]})"


_num_re = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def _is_num(s) -> bool:
    return isinstance(s, str) and not isinstance(s, QStr) and bool(_num_re.match(s))


_tok_re = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(n, "\\" + n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse(text: str) -> Node:
    """Parse the first top-level S-expression in ``text``."""
    stack: List[Node] = []
    root: Optional[Node] = None
    pos = 0
    n = len(text)
    match = _tok_re.match
    while pos < n:
        m = match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"S-expression syntax error near offset {pos}: {text[pos:pos+40]!r}")
        pos = m.end()
        op, cl, q, a = m.groups()
        if op:
            node = Node([], m.start(1))
            if stack:
                stack[-1].items.append(node)
            stack.append(node)
        elif cl:
            if not stack:
                raise ValueError(f"Unbalanced ')' at offset {m.start(2)}")
            node = stack.pop()
            node.end = m.end(2)
            if not stack:
                root = node
                break
        elif q is not None:
            if not stack:
                continue
            stack[-1].items.append(QStr(_unescape(q)))
        elif a is not None:
            if not stack:
                continue
            stack[-1].items.append(a)
    if stack:
        raise ValueError("Unexpected end of file: unbalanced '('")
    if root is None:
        raise ValueError("No S-expression found")
    return root


def parse_file(path) -> Node:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


# ---------------------------------------------------------------- writing
def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _atom(a) -> str:
    if isinstance(a, QStr):
        return quote(a)
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, float):
        return fmt_num(a)
    if isinstance(a, int):
        return str(a)
    s = str(a)
    if s == "" or re.search(r'[\s()"]', s):
        return quote(s)
    return s


def fmt_num(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# Nodes that KiCad keeps on one line.
_INLINE = {"at", "xy", "size", "pts_short", "stroke_short", "color", "font", "offset", "length",
           "uuid", "width", "type", "effects_short", "justify", "start", "end", "mid", "center",
           "layer", "layers", "net", "drill", "rect_delta", "thickness", "fill_short", "lib_id",
           "reference", "unit", "exclude_from_sim", "in_bom", "on_board", "dnp", "hide", "number_short",
           "name_short", "pin_numbers", "pin_names", "roundrect_rratio", "radius", "angle", "version",
           "generator", "generator_version", "paper", "page", "diameter", "tstamp", "path_short"}


def dump(node, indent: int = 0, compact: bool = False) -> str:
    """Serialise a node (or nested python lists) to text."""
    if not isinstance(node, (Node, list)):
        return _atom(node)
    items = node.items if isinstance(node, Node) else node
    if compact:
        return "(" + " ".join(dump(i, 0, True) for i in items) + ")"
    head = items[0] if items and isinstance(items[0], str) else ""
    has_child_nodes = any(isinstance(i, (Node, list)) for i in items)
    if not has_child_nodes or head in _INLINE:
        return "(" + " ".join(dump(i, 0, True) for i in items) + ")"
    pad = "\t" * (indent + 1)
    parts = []
    line = "(" + " ".join(_atom(i) for i in _leading_atoms(items))
    rest = items[len(_leading_atoms(items)):]
    parts.append(line)
    for it in rest:
        if isinstance(it, (Node, list)):
            parts.append("\n" + pad + dump(it, indent + 1))
        else:
            parts.append(" " + _atom(it))
    parts.append("\n" + "\t" * indent + ")")
    return "".join(parts)


def _leading_atoms(items):
    out = []
    for i in items:
        if isinstance(i, (Node, list)):
            break
        out.append(i)
    return out


def L(*items) -> list:
    """Build a list-based S-expression quickly: L('at', 1.27, 2.54, 0)."""
    return list(items)


def Q(s) -> QStr:
    return QStr(s)
