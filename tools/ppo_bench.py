"""DriveNow advice on SUMO grids whose lights a PPO agent switches (Piano DriveNow, punti 7 e 9).

The lights are driven step by step by the PPO agent of MagMueller's repository
(https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control, the one
Traffc_light_control came from), trained with ``tools/ppo_train.py``. The future of such
lights is not known, so the advice gets only what the agent is committed to:
``drivenow.committed`` turns the current phase and its elapsed time into certain and likely
green windows.

Cases, all on the same cars (same route file per seed, see ``--seeds``):

* ``fixed``: the fixed-time cycle DriveNow installs (as in SumoWorld), the forecast is exact;
* ``ppo``: the PPO agent; ``timing`` gives the rules it is held to (``raw``: as trained,
  a decision every second and no minimum or maximum green; ``rules``: also a minimum and a
  maximum green, as SUMO-RL and GreenWave keep them);
* ``advice``: ``none`` (no car follows DriveNow), ``certain`` (only the certain windows,
  the windows_fn contract of LibSignalAdvisor) or ``committed`` (certain windows when they
  are all there is, otherwise the likely ones, flagged not certain).

Each run counts ``false_green_s``: seconds a light was not green inside a certain window
handed to the advice (must be 0), and reports stops, brake energy and travel time of the
trips completed after the warm-up.

    python tools/ppo_bench.py --ppo-repo ../ppo_ext --weights ../ppo_weights/ppo_2x2.pt \
        --seeds 1 2 3 --out docs/benchmarks/ppo-2x2

Needs SUMO and TraCI; with ``--weights`` also PyTorch and the external checkout. Without
``--weights`` the agent is ``random`` (switches with probability 0.1 at each allowed
decision): a check of the windows, not of the PPO. Not a server dependency.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from drivenow.committed import GREEN, AgentTiming, CommittedSignalSource  # noqa: E402
from drivenow.network import load_sumo_net  # noqa: E402
from drivenow.simulation import GroupStats  # noqa: E402
from drivenow.sumo_world import SumoWorld  # noqa: E402

NET_DIR = os.path.join(REPO, "data", "sumo")
TIMINGS = {
    # As the repository trains it: a decision each simulated second, switching (through the
    # 3 s yellow) whenever the agent asks, except during a yellow.
    "raw": AgentTiming(min_green=0.0, max_green=None, yellow=3.0, decision_interval=1.0),
    # The same agent held to a minimum and a maximum green (SUMO-RL keeps min_green = 5 s;
    # GreenWave a 90 s maximum, here 60 s).
    "rules": AgentTiming(min_green=5.0, max_green=60.0, yellow=3.0, decision_interval=1.0),
}
DET_LENGTH = 20 * (5 + 2.5)   # the repository's detectors: 20 cars of 5 m with 2.5 m gaps

Policy = Callable[[Dict[str, List[float]], float], Dict[str, int]]


# -- the agent's view: the repository's state, read from SUMO ---------------------------

def intersections(net_path: str) -> List[str]:
    """Agent order: the net's non-internal junctions named ``intersection...``, in file order."""
    root = ET.parse(net_path).getroot()
    return [j.attrib["id"] for j in root.iter("junction")
            if j.attrib.get("type") != "internal" and "intersection" in j.attrib["id"]]


def detectors(net_path: str) -> Dict[str, List[tuple]]:
    """Intersection -> [(detector id, lane, pos, end)], one lane-area detector at the end of each
    edge into it, in the net's edge order (the order of the state vector)."""
    out: Dict[str, List[tuple]] = {}
    for e in ET.parse(net_path).getroot().iter("edge"):
        if "function" in e.attrib or "intersection" not in e.attrib.get("to", ""):
            continue
        length = float(e.find("lane").attrib["length"])
        out.setdefault(e.attrib["to"], []).append((f"DET+++{e.attrib['id']}", f"{e.attrib['id']}_0",
                                                   max(length - DET_LENGTH, 0.0), length))
    return out


def write_detectors(net_path: str, folder: str) -> str:
    path = os.path.join(folder, "agent_detectors.add.xml")
    out = os.path.join(folder, "agent_detectors.out.xml")
    with open(path, "w") as f:
        f.write("<additionals>\n")
        for dets in detectors(net_path).values():
            for det, lane, pos, end in dets:
                f.write(f'  <laneAreaDetector id="{det}" lane="{lane}" pos="{pos:.2f}" endPos="{end:.2f}" '
                        f'friendlyPos="true" period="100000" file="{out}"/>\n')
        f.write("</additionals>\n")
    return path


class AgentWorld(SumoWorld):
    """SumoWorld whose lights a policy switches, at each decision, within ``timing``."""

    def __init__(self, net_path: str, policy: Policy, timing: AgentTiming, advice: str = "committed",
                 **kwargs) -> None:
        self._det_tmp = tempfile.mkdtemp(prefix="drivenow_agent_")
        super().__init__(net_path, additional=write_detectors(net_path, self._det_tmp), **kwargs)
        self.policy, self.timing = policy, timing
        self.agents = intersections(self.net_path)
        self.dets = detectors(self.net_path)
        tl = self.conn.trafficlight
        for a in self.agents:   # the repository's own program: 100000 s greens the agent ends
            tl.setProgram(a, "0")
            tl.setPhase(a, 0)
        self.source = CommittedSignalSource(self.conn, self.net_path, timing,
                                            mode="certain" if advice == "none" else advice, record=True)
        self.advisor.windows_fn = self.source
        self.false_green = 0.0
        self.switches = self.forced = self.refused = 0

    def agent_state(self) -> Dict[str, List[float]]:
        """The repository's per-intersection state, unnormalised: jam length (cars) of each
        detector, current phase, seconds in it."""
        c, now = self.conn, self.conn.simulation.getTime()
        out = {}
        for a in self.agents:
            jams = [float(c.lanearea.getJamLengthVehicle(d[0])) if now > 0 else 0.0 for d in self.dets[a]]
            elapsed = c.trafficlight.getPhaseDuration(a) - (c.trafficlight.getNextSwitch(a) - now)
            out[a] = jams + [float(c.trafficlight.getPhase(a)), elapsed]
        return out

    def _before_step(self) -> None:
        t = self.t
        if abs(self.timing.decision_at_or_after(t - self.dt / 2) - t) > self.dt / 2:
            return
        tl = self.conn.trafficlight
        wants = self.policy(self.agent_state(), t)
        for a in self.agents:
            phase = tl.getPhase(a)
            if phase % 2 == 1:
                continue                      # yellow: the change is under way
            elapsed = tl.getPhaseDuration(a) - (tl.getNextSwitch(a) - t)
            maxed = self.timing.max_green is not None and elapsed >= self.timing.max_green - 1e-6
            if maxed or (wants.get(a) == 1 and elapsed >= self.timing.min_green - 1e-6):
                tl.setPhase(a, phase + 1)
                self.switches += 1
                self.forced += bool(maxed and wants.get(a) != 1)
            elif wants.get(a) == 1:
                self.refused += 1

    def step(self) -> None:
        super().step()
        if self.source.check(self.t, tolerance=self.dt / 2):
            self.false_green += self.dt

    def close(self) -> None:
        super().close()
        shutil.rmtree(self._det_tmp, ignore_errors=True)


# -- policies ----------------------------------------------------------------------------

def random_policy(seed: int, p: float = 0.1) -> Policy:
    rng = random.Random(seed)
    return lambda state, t: {a: int(rng.random() < p) for a in state}


class PPOPolicy:
    """The trained PPO: the repository's NN_Model, imported from its checkout, fed its state."""

    def __init__(self, ppo_repo: str, weights: str, seed: int, max_ep_steps: int = 1250,
                 hidden: int = 32) -> None:
        from tools.ppo_train import import_external

        import_external(ppo_repo)
        import torch
        from models.ppo_model import NN_Model

        self.torch = torch
        state = torch.load(weights, map_location="cpu")
        size = state["body_model.model.0.weight"].shape[1]
        self.nn = NN_Model(size, 2, hidden, torch.device("cpu"))
        self.nn.load_state_dict(state)
        self.nn.eval()
        self.norm_t = max_ep_steps / 10.0
        self.gen = torch.Generator().manual_seed(seed)

    def __call__(self, state: Dict[str, List[float]], t: float) -> Dict[str, int]:
        names = list(state)
        rows = [s[:-1] + [s[-1] / 10.0, t / self.norm_t] for s in (state[n] for n in names)]
        with self.torch.no_grad():
            out = self.nn.body_model(self.torch.tensor(rows, dtype=self.torch.float32))
            logits = self.nn.actor_model(out)
            # The repository samples its action (Categorical); the same draw, from a seeded generator.
            acts = self.torch.multinomial(self.torch.softmax(logits, -1), 1, generator=self.gen).squeeze(-1)
        return {n: int(a) for n, a in zip(names, acts.tolist())}


# -- runs --------------------------------------------------------------------------------

def write_routes(net_path: str, demand: float, duration: float, seed: int, folder: str) -> str:
    """The cars of one seed, written once and given to every case (Piano, punto 9)."""
    os.makedirs(folder, exist_ok=True)
    fake = SimpleNamespace(net=load_sumo_net(net_path), rng=random.Random(seed), _tmp=folder)
    SumoWorld._write_routes(fake, demand, duration)
    return fake._route_file


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_case(net_path: str, controller: str, timing: str, advice: str, seed: int, route_file: str,
             until: float, warmup: float, policy_factory: Optional[Callable[[int], Policy]] = None,
             dt: float = 0.2) -> Dict:
    penetration = 0.0 if advice == "none" else 1.0
    label = f"bench_{controller}_{timing}_{advice}_{seed}_{os.getpid()}"
    t0 = time.time()
    if controller == "fixed":
        w = SumoWorld(net_path, penetration=penetration, seed=seed, dt=dt, route_file=route_file, label=label)
    else:
        w = AgentWorld(net_path, policy_factory(seed), TIMINGS[timing], advice=advice,
                       penetration=penetration, seed=seed, dt=dt, route_file=route_file, label=label)
    reset = False
    try:
        while w.t < until - 1e-9:
            if not reset and w.t >= warmup:
                w.stats = {True: GroupStats(), False: GroupStats()}
                reset = True
            w.step()
        both = GroupStats()
        for g in w.stats.values():
            for k, v in vars(g).items():
                setattr(both, k, getattr(both, k) + v)
        s = both.summary()
        row = {
            "controller": controller, "timing": timing if controller != "fixed" else "",
            "advice": advice, "seed": seed, "penetration": penetration,
            "trips": s["trips"], "travel_time_s": s["travel_time"], "stops": s["stops"],
            "brake_energy_kj": s["brake_energy_kj"], "red_runs": s["red_runs"],
            "false_green_s": round(getattr(w, "false_green", 0.0), 1),
            "certain_windows": getattr(getattr(w, "source", None), "certain_given", ""),
            "likely_windows": getattr(getattr(w, "source", None), "likely_given", ""),
            "switches": getattr(w, "switches", ""), "forced": getattr(w, "forced", ""),
            "refused": getattr(w, "refused", ""), "wall_s": round(time.time() - t0, 1),
        }
    finally:
        w.close()
    return row


CASES = [("fixed", "", "none"), ("fixed", "", "plan"),
         ("ppo", "raw", "none"), ("ppo", "raw", "certain"), ("ppo", "raw", "committed"),
         ("ppo", "rules", "none"), ("ppo", "rules", "certain"), ("ppo", "rules", "committed")]


def summarise(rows: Sequence[Dict]) -> List[Dict]:
    """Mean and spread over seeds per case, and the change against the same controller without advice."""
    import statistics as st

    keys = ("trips", "travel_time_s", "stops", "brake_energy_kj", "false_green_s")
    groups: Dict[tuple, List[Dict]] = {}
    for r in rows:
        groups.setdefault((r["controller"], r["timing"], r["advice"]), []).append(r)
    out = []
    for case, rs in groups.items():
        row = {"controller": case[0], "timing": case[1], "advice": case[2], "seeds": len(rs)}
        for k in keys:
            vals = [float(r[k]) for r in rs]
            row[k] = round(st.mean(vals), 2)
            row[k + "_sd"] = round(st.stdev(vals), 2) if len(vals) > 1 else 0.0
        base = groups.get((case[0], case[1], "none"))
        if base and case[2] != "none":
            for k in ("travel_time_s", "stops", "brake_energy_kj"):
                b = sum(float(r[k]) for r in base) / len(base)
                row[k + "_vs_none_pct"] = round(100 * (row[k] - b) / b, 1) if b else None
        out.append(row)
    return out


def markdown(summary: Sequence[Dict], meta: Dict) -> str:
    lines = [
        f"Rete `{meta['net']}`, domanda {meta['demand']} veicoli/h per ingresso per {meta['duration']} s, "
        f"simulazione fino a {meta['until']} s, riscaldamento {meta['warmup']} s (contano i viaggi conclusi dopo), "
        f"passo {meta['dt']} s, semi {', '.join(map(str, meta['seeds']))}, quota DriveNow 0 % (nessun consiglio) "
        f"o 100 %. Agente: {meta['agent']}.",
        "",
        "| Semafori | Regole | Consiglio | Viaggi | Tempo (s) | Fermate | Energia freni (kJ) | Δ tempo | Δ fermate | Δ energia | Verde promesso falso (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    names = {"fixed": "ciclo fisso", "ppo": "PPO"}
    rules = {"": "–", "raw": "come addestrato", "rules": "verde 5-60 s"}
    adv = {"none": "nessuno", "plan": "piano noto", "certain": "solo certe", "committed": "certe + probabili"}

    def pm(r, k):
        return f"{r[k]:g} ± {r[k + '_sd']:g}"

    def pct(r, k):
        v = r.get(k + "_vs_none_pct")
        return "" if v is None else f"{v:+.1f} %"

    for r in summary:
        lines.append(f"| {names[r['controller']]} | {rules[r['timing']]} | {adv[r['advice']]} | {r['trips']:g} | "
                     f"{pm(r, 'travel_time_s')} | {pm(r, 'stops')} | {pm(r, 'brake_energy_kj')} | "
                     f"{pct(r, 'travel_time_s')} | {pct(r, 'stops')} | {pct(r, 'brake_energy_kj')} | "
                     f"{r['false_green_s']:g} |")
    lines.append("")
    lines.append("Media ± deviazione standard tra i semi; Δ rispetto agli stessi semafori senza consiglio.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--net", default=os.path.join(NET_DIR, "2_2_intersections.net.xml"))
    ap.add_argument("--ppo-repo", help="checkout of the external repository (with --weights)")
    ap.add_argument("--weights", help="weights from tools/ppo_train.py; without: a random agent")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    # The repository spawns a car at each entry with probability 0.06 a second (216 an hour)
    # for 1000 s and ends its episodes at 1250 s; its agent sees the time normalised to that.
    ap.add_argument("--demand", type=float, default=216.0, help="vehicles/h per entry")
    ap.add_argument("--duration", type=float, default=1000.0, help="s of departures")
    ap.add_argument("--until", type=float, default=1250.0, help="s simulated")
    ap.add_argument("--warmup", type=float, default=200.0)
    ap.add_argument("--dt", type=float, default=0.2)
    ap.add_argument("--cases", nargs="+", help="controller:timing:advice, e.g. ppo:rules:committed")
    ap.add_argument("--out", help="write OUT.csv, OUT.json and OUT.md")
    args = ap.parse_args(argv)

    if args.weights:
        if not args.ppo_repo:
            raise SystemExit("--weights needs --ppo-repo")
        weights = os.path.abspath(args.weights)
        factory = lambda seed: PPOPolicy(args.ppo_repo, weights, seed)  # noqa: E731
        note = os.path.splitext(weights)[0] + ".json"
        agent = {"kind": "ppo", "weights_sha256": sha256(weights)}
        if os.path.exists(note):
            with open(note) as f:
                agent["training"] = json.load(f)
        agent_text = f"PPO del repository MagMueller, pesi sha256 {agent['weights_sha256'][:12]}"
    else:
        factory = random_policy
        agent = {"kind": "random", "p_switch": 0.1}
        agent_text = "casuale (cambia con probabilità 0,1 a ogni decisione consentita), solo per provare le finestre"
    cases = [tuple(c.split(":")) for c in args.cases] if args.cases else CASES
    tmp = tempfile.mkdtemp(prefix="drivenow_bench_")
    rows, routes = [], {}
    try:
        for seed in args.seeds:
            route_file = write_routes(args.net, args.demand, args.duration, seed, tmp)
            kept = os.path.join(tmp, f"routes_{seed}.rou.xml")
            os.replace(route_file, kept)
            routes[seed] = sha256(kept)
            for controller, timing, advice in cases:
                row = run_case(args.net, controller, timing, advice, seed, kept, args.until, args.warmup,
                               factory, args.dt)
                rows.append(row)
                print(json.dumps(row), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    summary = summarise(rows)
    meta = {"net": os.path.basename(args.net), "demand": args.demand, "duration": args.duration,
            "until": args.until, "warmup": args.warmup, "dt": args.dt, "seeds": args.seeds,
            "routes_sha256": routes, "agent": agent_text, "agent_detail": agent,
            "timings": {k: vars(v) for k, v in TIMINGS.items()}}
    text = markdown(summary, meta)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out + ".csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            wr.writeheader()
            wr.writerows(rows)
        with open(args.out + ".json", "w") as f:
            json.dump({"meta": meta, "summary": summary, "runs": rows}, f, indent=2)
        with open(args.out + ".md", "w") as f:
            f.write(text)
    return 0 if all(r["false_green_s"] == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
