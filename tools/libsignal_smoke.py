"""Exercise the bridge against the real pinned LibSignal SUMO World, without RL."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drivenow.libsignal import LibSignalAdvisor
from drivenow.network import load_sumo_net

REVISION = '127af9f93902778e556de2eedb2b606c4c9447e6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libsignal-root', type=Path, required=True)
    args = parser.parse_args()
    source = args.libsignal_root.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        parser.error(f'Use the verified LibSignal revision {REVISION}')
    import sumo
    os.environ.setdefault('SUMO_HOME', sumo.SUMO_HOME)
    sys.path.insert(0, str(source))
    # Load only the actual SUMO module: upstream world/__init__.py also imports
    # CityFlow, which is unnecessary for this SUMO-only compatibility check.
    spec = importlib.util.spec_from_file_location('libsignal_sumo', source / 'world/world_sumo.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from common.registry import Registry

    net_file = ROOT / 'data/sumo/1_1_intersections.net.xml'
    net = load_sumo_net(str(net_file))
    route = [net.entry_edges()[0]]
    route += net.path_to_border(route[0])
    with tempfile.TemporaryDirectory(prefix='drivenow_libsignal_') as directory:
        temp = Path(directory)
        routes = temp / 'routes.rou.xml'
        routes.write_text('<routes><vType id="car" speedFactor="1"/>' + ''.join(
            f'<vehicle id="car{i}" type="car" depart="{2*i}"><route edges="{" ".join(route)}"/></vehicle>'
            for i in range(40)) + '</routes>')
        config = temp / 'sumo.json'
        config.write_text(json.dumps({'dir': str(temp), 'roadnetFile': str(net_file),
                                     'flowFile': str(routes), 'no_warning': True,
                                     'name': 'drivenow_libsignal', 'interval': 1, 'gui': False}))
        Registry.mapping['logger_mapping']['path'] = SimpleNamespace(path=str(temp))
        world = module.World(str(config), interface='traci')
        world.reset()
        bridge = LibSignalAdvisor(world, penetration=1, seed=1)
        observed = 0
        try:
            for tick in range(90):
                actions = [(tick // 20) % len(inter.phases) for inter in world.intersections]
                world.step(actions)
                before = {tls: world.eng.trafficlight.getRedYellowGreenState(tls)
                          for tls in world.intersection_ids}
                observed += len(bridge.step(apply=True))
                after = {tls: world.eng.trafficlight.getRedYellowGreenState(tls)
                         for tls in world.intersection_ids}
                assert before == after, 'The adapter changed signal states'
            assert observed > 0, 'No live vehicles were observed'
            print(json.dumps({'status': 'passed', 'libsignal_revision': revision,
                              'ticks': 90, 'vehicle_advice_samples': observed,
                              'signal_forecast': 'unknown; no fabricated green windows',
                              'benchmark': False}, indent=2))
        finally:
            bridge.release()
            world.eng.close()


if __name__ == '__main__':
    main()
