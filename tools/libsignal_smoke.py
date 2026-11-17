"""Exercise the bridge against the real pinned LibSignal SUMO World, without RL."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drivenow.libsignal import LibSignalAdvisor
from drivenow.network import load_sumo_net

REVISION = '127af9f93902778e556de2eedb2b606c4c9447e6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libsignal-root', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=90)
    parser.add_argument('--learn-signals', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.steps <= 3600:
        parser.error('steps must be between 1 and 3600')
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
    straight = next((edge for edge in net.edges[route[0]].next_edges if net.turn(route[0], edge) == 's'), None)
    if straight:
        route.append(straight)
        route += net.path_to_border(straight)
    else:
        route += net.path_to_border(route[0])
    with tempfile.TemporaryDirectory(prefix='drivenow_libsignal_') as directory:
        temp = Path(directory)
        # The source grid uses 100000s phases for externally controlled lights.
        # Let LibSignal discover both green phases during its 500-step startup,
        # using a temporary fixture only; never change the repository network.
        tree = ET.parse(net_file)
        for phase in tree.getroot().iter('phase'):
            phase.set('duration', '3' if 'y' in phase.get('state','') else '20')
        net_file = temp / 'fixture.net.xml'
        tree.write(net_file)
        routes = temp / 'routes.rou.xml'
        routes.write_text('<routes><vType id="car" speedFactor="1"/>' + ''.join(
            f'<vehicle id="car{i}" type="car" depart="{2*i}"><route edges="{" ".join(route)}"/></vehicle>'
            for i in range(max(40, args.steps // 4))) + '</routes>')
        config = temp / 'sumo.json'
        config.write_text(json.dumps({'dir': str(temp), 'roadnetFile': str(net_file),
                                     'flowFile': str(routes), 'no_warning': True,
                                     'name': 'drivenow_libsignal', 'interval': 1, 'gui': False}))
        Registry.mapping['logger_mapping']['path'] = SimpleNamespace(path=str(temp))
        world = module.World(str(config), interface='traci')
        world.reset()
        bridge = LibSignalAdvisor(world, penetration=1, seed=1, learn_signals=args.learn_signals)
        observed = 0
        try:
            for tick in range(args.steps):
                actions = [(tick // 20) % len(inter.phases) for inter in world.intersections]
                world.step(actions)
                before = {tls: world.eng.trafficlight.getRedYellowGreenState(tls)
                          for tls in world.intersection_ids}
                observed += len(bridge.step(apply=True))
                after = {tls: world.eng.trafficlight.getRedYellowGreenState(tls)
                         for tls in world.intersection_ids}
                assert before == after, 'The adapter changed signal states'
            assert observed > 0, 'No live vehicles were observed'
            source = bridge.signal_source
            if args.learn_signals and args.steps >= 900:
                assert source.nonempty_forecasts > 0, 'The live predictor did not produce green windows'
            print(json.dumps({'status': 'passed', 'libsignal_revision': revision,
                              'ticks': args.steps,
                              'learned_forecasts': source.forecasts if source else 0,
                              'nonempty_green_forecasts': source.nonempty_forecasts if source else 0, 'vehicle_advice_samples': observed,
                              'signal_forecast': 'learned from past observations' if source else 'unknown; no fabricated green windows',
                              'benchmark': False}, indent=2))
        finally:
            bridge.release()
            world.eng.close()


if __name__ == '__main__':
    main()
