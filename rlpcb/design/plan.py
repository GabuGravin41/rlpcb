"""Design plan: the intended circuit, independent of how it is drawn.

The copilot and the engineer agree on a *plan* (components + nets). The plan is
the source of truth that drives:
  * symbol placement (no wires are ever drawn by the AI),
  * step-by-step wiring instructions,
  * verification of the hand-drawn schematic (what's missing / wrong / extra),
  * PCB guidance (net classes, widths, placement groups).

Stored as JSON next to the project: <project>/.rlpcb/plan.json
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

PLAN_VERSION = 1


@dataclass
class PlanComponent:
    ref: str
    lib_id: str
    value: str = ""
    footprint: str = ""
    block: str = ""
    role: str = ""  # human description of why it exists
    fields: Dict[str, str] = field(default_factory=dict)
    notes: str = ""
    unit_count: int = 1
    dnp: bool = False
    sheet: str = ""  # target sheet file (relative) or "" for root


@dataclass
class PlanNet:
    name: str
    nodes: List[str] = field(default_factory=list)  # "U1.3" (pin number) — names resolved on add
    net_class: str = ""  # power | ground | signal | high_speed | diff_pair | analog | high_voltage | rf
    notes: str = ""
    width_mm: Optional[float] = None
    diff_partner: Optional[str] = None
    impedance_ohm: Optional[float] = None
    max_length_mm: Optional[float] = None
    current_a: Optional[float] = None
    voltage_v: Optional[float] = None


@dataclass
class PlanBlock:
    id: str
    title: str
    purpose: str = ""
    notes: str = ""
    layout_notes: str = ""
    reference_design: str = ""


@dataclass
class DesignPlan:
    name: str
    description: str = ""
    blocks: List[PlanBlock] = field(default_factory=list)
    components: List[PlanComponent] = field(default_factory=list)
    nets: List[PlanNet] = field(default_factory=list)
    no_connect: List[str] = field(default_factory=list)
    requirements: Dict[str, str] = field(default_factory=dict)  # free-form spec: input voltage, currents, env
    decisions: List[str] = field(default_factory=list)  # design decisions log with rationale
    version: int = PLAN_VERSION
    updated: float = 0.0

    # ---------------------------------------------------------------- io
    @staticmethod
    def path_for(project_dir: str) -> str:
        return os.path.join(project_dir, ".rlpcb", "plan.json")

    @classmethod
    def load(cls, project_dir: str) -> "DesignPlan":
        p = cls.path_for(project_dir)
        with open(p, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def load_or_new(cls, project_dir: str, name: str = "") -> "DesignPlan":
        try:
            return cls.load(project_dir)
        except (OSError, ValueError):
            return cls(name=name or os.path.basename(os.path.normpath(project_dir)))

    def save(self, project_dir: str) -> str:
        p = self.path_for(project_dir)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self.updated = time.time()
        if os.path.exists(p):  # keep history: at most one snapshot per 5 minutes, newest 200 kept
            hist = os.path.join(os.path.dirname(p), "history")
            os.makedirs(hist, exist_ok=True)
            snaps = sorted(f for f in os.listdir(hist) if f.startswith("plan-"))
            last = int(snaps[-1][5:-5]) if snaps and snaps[-1][5:-5].isdigit() else 0
            if time.time() - last > 300:
                try:
                    import shutil
                    shutil.copy2(p, os.path.join(hist, f"plan-{int(time.time())}.json"))
                except OSError:
                    pass
                for old in snaps[:-200]:
                    try:
                        os.remove(os.path.join(hist, old))
                    except OSError:
                        pass
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return p

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignPlan":
        d = copy.deepcopy(d)
        plan = cls(name=d.get("name", "design"))
        plan.description = d.get("description", "")
        plan.blocks = [PlanBlock(**_known(PlanBlock, b)) for b in d.get("blocks", [])]
        plan.components = [PlanComponent(**_known(PlanComponent, c)) for c in d.get("components", [])]
        plan.nets = [PlanNet(**_known(PlanNet, n)) for n in d.get("nets", [])]
        plan.no_connect = list(d.get("no_connect", []))
        plan.requirements = dict(d.get("requirements", {}))
        plan.decisions = list(d.get("decisions", []))
        plan.updated = d.get("updated", 0.0)
        return plan

    # ------------------------------------------------------------ lookup
    def comp(self, ref: str) -> Optional[PlanComponent]:
        for c in self.components:
            if c.ref == ref:
                return c
        return None

    def net(self, name: str) -> Optional[PlanNet]:
        for n in self.nets:
            if n.name == name:
                return n
        return None

    def node_net(self) -> Dict[str, str]:
        out = {}
        for n in self.nets:
            for node in n.nodes:
                out[node] = n.name
        return out

    def next_ref(self, prefix: str, taken: Optional[set] = None) -> str:
        taken = set(taken or ()) | {c.ref for c in self.components}
        i = 1
        while f"{prefix}{i}" in taken:
            i += 1
        return f"{prefix}{i}"

    # ------------------------------------------------------------ editing
    def upsert_component(self, c: PlanComponent) -> PlanComponent:
        old = self.comp(c.ref)
        if old:
            for k, v in asdict(c).items():
                if v not in (None, "", {}, []):
                    setattr(old, k, v)
            return old
        self.components.append(c)
        return c

    def remove_component(self, ref: str):
        self.components = [c for c in self.components if c.ref != ref]
        for n in self.nets:
            n.nodes = [x for x in n.nodes if x.split(".", 1)[0] != ref]
        self.no_connect = [x for x in self.no_connect if x.split(".", 1)[0] != ref]

    def connect(self, net_name: str, nodes: List[str], **attrs) -> Tuple[PlanNet, List[str]]:
        """Add nodes to a net. A node already on another net is moved, and the move is reported."""
        moved = []
        owner = self.node_net()
        net = self.net(net_name)
        if net is None:
            net = PlanNet(name=net_name)
            self.nets.append(net)
        for k, v in attrs.items():
            if v is not None and hasattr(net, k):
                setattr(net, k, v)
        for node in nodes:
            prev = owner.get(node)
            if prev and prev != net_name:
                pn = self.net(prev)
                pn.nodes = [x for x in pn.nodes if x != node]
                moved.append(f"{node} moved from {prev} to {net_name}")
            if node not in net.nodes:
                net.nodes.append(node)
            if node in self.no_connect:
                self.no_connect.remove(node)
        self.nets = [n for n in self.nets if n.nodes or n.name == net_name]
        return net, moved

    def disconnect(self, nodes: List[str]):
        for n in self.nets:
            n.nodes = [x for x in n.nodes if x not in nodes]
        self.nets = [n for n in self.nets if n.nodes]

    def rename_net(self, old: str, new: str):
        n = self.net(old)
        if n is None:
            raise KeyError(old)
        other = self.net(new)
        if other is not None:
            other.nodes += [x for x in n.nodes if x not in other.nodes]
            self.nets.remove(n)
        else:
            n.name = new

    # ------------------------------------------------------------ summary
    def summary(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "requirements": self.requirements,
            "blocks": [asdict(b) for b in self.blocks],
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "components": [{"ref": c.ref, "lib_id": c.lib_id, "value": c.value, "footprint": c.footprint,
                            "block": c.block, "role": c.role} for c in sorted(self.components, key=lambda c: _natref(c.ref))],
            "nets": [{"name": n.name, "class": n.net_class, "nodes": n.nodes, "notes": n.notes} for n in self.nets],
            "no_connect": self.no_connect,
            "decisions": self.decisions,
        }


def _known(cls, d):
    names = set(cls.__dataclass_fields__.keys())
    return {k: v for k, v in d.items() if k in names}


def _natref(ref):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref)]


# ------------------------------------------------------------------ pin resolution
class PinResolver:
    """Resolve 'U1.3', 'U1.VIN', 'U1.GND*' against symbol pin data from the library index or a lib symbol."""

    def __init__(self, pin_lookup):
        # pin_lookup(lib_id) -> list of {"number","name","type","unit"?}
        self.pin_lookup = pin_lookup

    def resolve(self, plan: DesignPlan, spec: str) -> Tuple[List[str], Optional[str]]:
        if "." not in spec:
            return [], f"'{spec}' must look like REF.PIN (e.g. U1.3 or U1.VIN)"
        ref, pin = spec.split(".", 1)
        comp = plan.comp(ref)
        if comp is None:
            return [], f"No component {ref} in the plan (add it first)"
        pins = self.pin_lookup(comp.lib_id) or []
        if not pins:
            return [f"{ref}.{pin}"], None  # unknown symbol pins; accept as-is
        numbers = {p["number"] for p in pins}
        if pin in numbers:
            return [f"{ref}.{pin}"], None
        wildcard = pin.endswith("*")
        base = pin.rstrip("*").lower()
        by_name = sorted({p["number"] for p in pins if _pin_name_match(p["name"], base, wildcard)}, key=_natref)
        if by_name:
            return [f"{ref}.{n}" for n in by_name], None
        # tolerant match: GPIO20 == IO20 == P20, D+ == DP, VIN == VI, ~{RESET} == RESET ...
        want = _norm_pin(pin)
        by_norm = sorted({p["number"] for p in pins if _norm_pin(p["name"]) == want or
                          any(_norm_pin(part) == want for part in p["name"].split("/"))}, key=_natref)
        if by_norm:
            return [f"{ref}.{n}" for n in by_norm], None
        names = sorted({p["name"] for p in pins if p["name"] not in ("~", "")})
        import difflib
        close = difflib.get_close_matches(pin.upper(), [n.upper() for n in names], n=5, cutoff=0.5)
        return [], (f"{comp.lib_id} ({ref}) has no pin '{pin}'."
                    + (f" Did you mean: {', '.join(close)}?" if close else "")
                    + f" Pin numbers: {', '.join(sorted(numbers, key=_natref)[:80])}"
                    + (f"; pin names: {', '.join(names[:80])}" if names else ""))


def _clean_pin_name(n: str) -> str:
    return re.sub(r"[~{}]", "", n).lower()


def _pin_name_match(name: str, base: str, wildcard: bool) -> bool:
    n = _clean_pin_name(name)
    if wildcard:
        return n.startswith(base)
    if n == base:
        return True
    # multi-function pins "PA9/USART1_TX": match a slash-separated function
    return base in n.split("/")


def _norm_pin(n: str) -> str:
    n = re.sub(r"[~{}\s_\-]", "", n).upper()
    n = n.replace("+", "P").replace("GPIO", "IO")
    n = re.sub(r"^P(?=\d)", "IO", n)          # P20 -> IO20
    n = re.sub(r"^IO0*(\d)", r"IO\1", n)       # IO05 -> IO5
    return {"VIN": "VI", "VOUT": "VO", "DM": "D-", "DN": "D-"}.get(n, n).replace("-", "M")
