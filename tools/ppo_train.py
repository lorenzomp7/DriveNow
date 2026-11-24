"""Train the PPO traffic-light agent of MagMueller's repository on a grid, weights kept outside.

The repository (https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control)
is the one Traffc_light_control, and so DriveNow, came from: same ``.net.xml`` grids, same
SUMO. It declares no licence, so DriveNow does not copy its code: this script imports it
from a separate checkout (``--ppo-repo``) and drives its own classes (``IntersectionsEnv``,
``NN_Model``, ``PPOWorker``) in a single process, headless. The repository is the git
submodule ``third_party/ppo-traffic-light`` (a pinned link, not a copy); the weights go to
``data/ppo/`` with a JSON note next to them (settings, rollouts, time, the external commit).

    python tools/devtools.py setup ppo        # submodule + environment (requirements-ppo.txt)
    python tools/ppo_train.py --rollouts 200  # about 20 minutes on 2 CPUs

Not a server dependency: ``python -m drivenow.server`` never imports this.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PPO_REPO = os.path.join(REPO, "third_party", "ppo-traffic-light")
WEIGHTS = os.path.join(REPO, "data", "ppo", "ppo_2x2.pt")


def import_external(ppo_repo: str):
    """Put the external checkout on the path; SUMO_HOME from the eclipse-sumo wheel if unset."""
    ppo_repo = os.path.abspath(ppo_repo)
    if not os.path.isfile(os.path.join(ppo_repo, "models", "ppo_model.py")):
        raise SystemExit(f"{ppo_repo}: not a checkout of Multi-Agent-Distributed-PPO-Traffc-light-control "
                         "(git submodule update --init third_party/ppo-traffic-light)")
    if "SUMO_HOME" not in os.environ:
        import sumo  # the eclipse-sumo wheel

        os.environ["SUMO_HOME"] = sumo.SUMO_HOME
    if ppo_repo not in sys.path:
        sys.path.insert(0, ppo_repo)
    # The repository (2023) reads traci.main._connections; current TraCI keeps them in traci.connection.
    import traci.connection
    import traci.main

    # Its close() also deletes the label, which current TraCI has already dropped when closing.
    if not hasattr(traci.main, "_connections"):
        class _Connections(dict):
            def __contains__(self, label):
                return label in traci.connection._connections

            def __delitem__(self, label):
                traci.connection._connections.pop(label, None)

        traci.main._connections = _Connections()
    # It also uses np.float and np.int, removed in NumPy 1.24.
    import numpy as np

    for alias, kind in (("float", float), ("int", int)):
        if alias not in np.__dict__:
            setattr(np, alias, kind)
    return ppo_repo


def external_commit(ppo_repo: str) -> str:
    try:
        return subprocess.run(["git", "-C", ppo_repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ppo-repo", default=PPO_REPO, help="checkout of the repository (default: the submodule)")
    ap.add_argument("--out", default=WEIGHTS, help="weights file (.pt), default data/ppo/ppo_2x2.pt")
    ap.add_argument("--shape", type=int, nargs=2, default=[2, 2], help="grid: 1 1, 2 2, 3 3 or 4 4")
    ap.add_argument("--rollouts", type=int, default=150, help="training rollouts (the repository uses 300)")
    ap.add_argument("--rollout-length", type=int, default=None, help="steps per rollout (repository: 2048)")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    ppo_repo = import_external(args.ppo_repo)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    import random

    import numpy as np
    import torch

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    os.chdir(ppo_repo)  # the repository writes its route, config and detector files under data/
    from environments.intersections import ACTION_SIZE, GLOBAL_STATE_SIZE, PER_AGENT_STATE_SIZE, IntersectionsEnv
    from models.ppo_model import NN_Model
    from utils.net_scrape import get_intersection_neighborhoods
    from utils.utils import get_net_path, get_state_action_size, load_constants
    from workers.ppo_worker import PPOWorker

    constants = load_constants("constants/constants.json")
    constants["environment"]["shape"] = list(args.shape)
    constants["agent"] = {"agent_type": "ppo", "single_agent": False}
    constants["episode"]["num_train_rollouts"] = args.rollouts
    if args.rollout_length:
        constants["episode"]["rollout_length"] = args.rollout_length
    device = torch.device("cpu")
    net_path = get_net_path(constants)
    _, max_neighbors = get_intersection_neighborhoods(net_path)
    sizes = get_state_action_size(PER_AGENT_STATE_SIZE, GLOBAL_STATE_SIZE, ACTION_SIZE, max_neighbors, constants)
    hidden = constants["ppo"]["hidden_layer_size"]
    shared = NN_Model(sizes["s"], sizes["a"], hidden, device).to(device)
    local = NN_Model(sizes["s"], sizes["a"], hidden, device).to(device)
    opt = torch.optim.Adam(shared.parameters(), constants["ppo"]["learning_rate"])
    env = IntersectionsEnv(constants, device, "drivenow_train", False, net_path, vis=False)
    worker = PPOWorker(constants, device, env, None, shared, local, opt, "drivenow_train")

    t0 = time.time()
    steps = 0
    for k in range(1, args.rollouts + 1):
        steps = worker.train_rollout(steps)
        if k % 10 == 0 or k == args.rollouts:
            print(f"rollout {k}/{args.rollouts}  {time.time() - t0:.0f} s", flush=True)
    worker.env.connection.close()

    torch.save(shared.state_dict(), out)
    note = {
        "weights": os.path.basename(out),
        "external_repo": "https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control",
        "external_commit": external_commit(ppo_repo),
        "net": os.path.basename(net_path),
        "state_size": sizes["s"], "action_size": sizes["a"], "hidden_layer_size": hidden,
        "rollouts": args.rollouts, "rollout_length": constants["episode"]["rollout_length"],
        "max_ep_steps": constants["episode"]["max_ep_steps"],
        "generation_ep_steps": constants["episode"]["generation_ep_steps"],
        "uniform_generation_probability": constants["environment"]["uniform_generation_probability"],
        "ppo": constants["ppo"], "seed": args.seed, "train_seconds": round(time.time() - t0),
        "torch": torch.__version__, "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(os.path.splitext(out)[0] + ".json", "w") as f:
        json.dump(note, f, indent=2)
    print(f"weights: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
