"""Install, run and expose DriveNow's optional tools without shell activation."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REQUIREMENTS = {'browser':'requirements-ui.txt', 'vibetest':'requirements-vibetest.txt',
                'darts':'requirements-darts.txt', 'libsignal':'requirements-libsignal.txt',
                'container':'requirements-container-use.txt', 'ppo':'requirements-ppo.txt'}
NAMES = [*REQUIREMENTS, 'flameox', 'rea', 'playwriter', 'skills']
# Repositories integrated as git submodules (third_party/): pinned links, not copies.
SUBMODULES = {'ppo':'third_party/ppo-traffic-light', 'flameox':'third_party/flameox', 'rea':'third_party/rea'}
APKTOOL = ('https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar',
           '66cf4524a4a45a7f56567d08b2c9b6ec237bcdd78cee69fd4a59c8a0243aeafa')
TOOLS_BIN = ROOT / '.tools/bin'
REA_BIN = ROOT / '.tools/rea/node_modules/.bin' / ('rea.cmd' if os.name == 'nt' else 'rea')
LIBSIGNAL_REVISION = '127af9f93902778e556de2eedb2b606c4c9447e6'
LIBSIGNAL_ROOT = ROOT / '.tools/src/LibSignal'


@contextmanager
def demo_url():
    import threading
    from http.server import ThreadingHTTPServer
    from drivenow.network import demo_city
    from drivenow.server import Runner, make_handler
    from drivenow.simulation import Simulation, SimConfig
    runner = Runner(Simulation(demo_city(), SimConfig(seed=1, penetration=1, demand=600)), speed=5)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(runner))
    server.daemon_threads = True
    runner.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        runner._stop = True
        server.shutdown()
        server.server_close()


def python_for(name):
    return ROOT / '.tools/envs' / name / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def chrome_path():
    if os.environ.get('DRIVENOW_CHROMIUM'):
        path = Path(os.environ['DRIVENOW_CHROMIUM'])
        return str(path) if path.is_file() else None
    for name in ('google-chrome','google-chrome-stable','chromium','chromium-browser'):
        found = shutil.which(name)
        if found:
            return found
    if os.name == 'nt':
        for variable in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
            path = Path(os.environ.get(variable,'')) / 'Google/Chrome/Application/chrome.exe'
            if path.is_file():
                return str(path)
    path = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    return str(path) if path.is_file() else None


def execute(command, **kwargs):
    return subprocess.run([str(c) for c in command], cwd=ROOT, check=True, **kwargs)


def submodule(name):
    path = SUBMODULES[name]
    if not (ROOT / path / '.git').exists():
        execute(['git','submodule','update','--init','--depth','1',path])
    return ROOT / path


def rea_version():
    return json.loads((ROOT / SUBMODULES['rea'] / 'package.json').read_text())['version']


def install_apktool():
    import hashlib
    import urllib.request
    TOOLS_BIN.mkdir(parents=True, exist_ok=True)
    jar = TOOLS_BIN / 'apktool.jar'
    if not jar.is_file():
        with urllib.request.urlopen(APKTOOL[0]) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != APKTOOL[1]:
            raise RuntimeError('Apktool download does not match its pinned SHA-256')
        jar.write_bytes(data)
    if os.name == 'nt':
        (TOOLS_BIN / 'apktool.bat').write_text(f'@java -jar "{jar}" %*\r\n')
    else:
        wrapper = TOOLS_BIN / 'apktool'
        wrapper.write_text(f'#!/bin/sh\nexec java -jar "{jar}" "$@"\n')
        wrapper.chmod(0o755)


def setup(name):
    if name in SUBMODULES:
        submodule(name)
    if name in REQUIREMENTS:
        python = python_for(name)
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(python.parent.parent)
        execute([python, '-m','pip','install','-r', ROOT / REQUIREMENTS[name]])
        if name == 'browser':
            execute([python,'-m','pip','install','pytest==9.2.0'])
        if name in ('browser','vibetest') and chrome_path() is None:
            execute([python,'-m','playwright','install','chromium'])
    if name == 'playwriter':
        if not shutil.which('node') or not shutil.which('npm'):
            raise RuntimeError('Install Node 22+ and npm before Playwriter setup')
        execute(['npm.cmd' if os.name == 'nt' else 'npm','ci','--prefix','tools/playwriter','--no-audit','--no-fund'])
    if name == 'container':
        execute([sys.executable,'tools/container_use.py','install'])
    if name == 'flameox':
        python = python_for(name)
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(python.parent.parent)
        execute([python,'-m','pip','install','-e',f"{SUBMODULES['flameox']}[cpu]"])
    if name == 'rea':
        if not shutil.which('node') or not shutil.which('npm') or not shutil.which('java'):
            raise RuntimeError('Install Node 22+, npm and Java 17+ before REA setup')
        execute(['npm.cmd' if os.name == 'nt' else 'npm','install','--prefix','.tools/rea','--no-audit','--no-fund',
                 f'rea-agents@{rea_version()}'])
        install_apktool()
    if name == 'libsignal':
        if not LIBSIGNAL_ROOT.exists():
            LIBSIGNAL_ROOT.parent.mkdir(parents=True, exist_ok=True)
            execute(['git','clone','https://github.com/DaRL-LibSignal/LibSignal.git',LIBSIGNAL_ROOT])
            execute(['git','-C',LIBSIGNAL_ROOT,'checkout',LIBSIGNAL_REVISION])
        revision = subprocess.check_output(['git','-C',str(LIBSIGNAL_ROOT),'rev-parse','HEAD'], text=True).strip()
        if revision != LIBSIGNAL_REVISION:
            raise RuntimeError('The managed LibSignal checkout has changed; inspect it before updating')
    if name == 'skills':
        validate_skills()
    print(f'Installed: {name}', flush=True)


def validate_skills():
    import hashlib
    lock = json.loads((ROOT / '.agents/agent-skills.lock.json').read_text())
    for path, digest in lock['files'].items():
        if hashlib.sha256((ROOT / '.agents' / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Vendored workflow differs from its manifest: {path}')
    return len(lock['skills'])


def tool_command(name, extra=()):
    python = python_for(name)
    commands = {
        'browser':[python,'tests/browser/check_ui.py'],
        'vibetest':[python,'tools/vibetest_drive.py'],
        'darts':[python,'tools/darts_benchmark.py'],
        'libsignal':[python,'tools/libsignal_smoke.py','--libsignal-root',LIBSIGNAL_ROOT,'--steps','900','--learn-signals'],
        'container':[python,'tools/container_use_smoke.py'],
        'playwriter':[sys.executable,'tools/playwriter_check.py'],
        'ppo':[python,'tools/ppo_bench.py'],
        'flameox':[python.parent / ('flameox.exe' if os.name == 'nt' else 'flameox'),'capture','--provider','py-spy',
                   '--operation','rank_cpu_hotspots','--cwd',ROOT,'--',sys.executable,'tools/sim_profile.py','sim'],
    }
    if name not in commands:
        raise ValueError('This tool provides instructions, not an executable test')
    if (name in REQUIREMENTS or name == 'flameox') and not python.is_file():
        raise RuntimeError(f'Run python tools/devtools.py setup {name} first')
    return [*commands[name], *extra]


def status():
    result = {}
    for name in NAMES:
        installed = python_for(name).is_file() if name in REQUIREMENTS or name == 'flameox' else (
            (ROOT / 'tools/playwriter/node_modules/playwriter/bin.js').is_file() if name == 'playwriter' else
            REA_BIN.is_file() and (TOOLS_BIN / 'apktool.jar').is_file() if name == 'rea' else True)
        if name in SUBMODULES:
            installed = installed and (ROOT / SUBMODULES[name] / '.git').exists()
        if installed and name in REQUIREMENTS:
            modules = {'browser':['playwright'], 'vibetest':['vibetest','browser_use'],
                       'darts':['darts'], 'libsignal':['traci','sumo','libsumo'], 'container':['mcp'],
                       'ppo':['torch','traci','sumo']}[name]
            probe = 'import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(m) for m in ' + repr(modules) + '))'
            installed = subprocess.run([str(python_for(name)),'-c',probe], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=30).returncode == 0
        needs = []
        if name == 'vibetest':
            needs = [key for key in ('GOOGLE_API_KEY','VIBETEST_MODEL') if not os.environ.get(key)]
        if name == 'container':
            binary = ROOT / '.tools' / ('container-use.exe' if os.name == 'nt' else 'container-use')
            installed = installed and binary.is_file()
            docker = shutil.which('docker')
            if not docker or subprocess.run([docker,'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode:
                needs.append('running Docker engine')
        if name == 'playwriter' and not chrome_path():
            needs.append('Chrome/Chromium')
        result[name] = {'installed':installed, 'needs':needs, 'test_executed':False}
    return result


def mcp_config():
    return {'mcpServers':{name:{'command':sys.executable,
        'args':[str(ROOT / 'tools/devtools.py'),'mcp',name]}
        for name in ('playwriter','container','vibetest')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    install = commands.add_parser('setup')
    install.add_argument('names', nargs='*', choices=NAMES)
    commands.add_parser('status')
    commands.add_parser('mcp-config')
    run = commands.add_parser('run')
    run.add_argument('name', choices=NAMES)
    run.add_argument('extra', nargs=argparse.REMAINDER)
    mcp = commands.add_parser('mcp')
    mcp.add_argument('name', choices=['playwriter','container','vibetest'])
    args = parser.parse_args(argv)
    try:
        if args.action == 'setup':
            for name in args.names or NAMES:
                setup(name)
        elif args.action == 'status':
            print(json.dumps(status(), indent=2))
        elif args.action == 'mcp-config':
            print(json.dumps(mcp_config(), indent=2))
        elif args.action == 'run':
            if args.name == 'skills':
                print(f'{validate_skills()} workflows verified')
            else:
                extra = args.extra[1:] if args.extra[:1] == ['--'] else args.extra
                env = dict(os.environ)
                if chrome_path():
                    env['DRIVENOW_CHROMIUM'] = chrome_path()
                if args.name == 'vibetest' and not {'--check','--check-browser'}.intersection(extra) and not any(a == '--url' or a.startswith('--url=') for a in extra):
                    if not os.environ.get('GOOGLE_API_KEY'):
                        raise RuntimeError('Set GOOGLE_API_KEY to run AI QA; no API call was made')
                    with demo_url() as url:
                        execute(tool_command(args.name, ['--url',url,*extra]), env=env)
                else:
                    execute(tool_command(args.name, extra), env=env)
        else:
            name = args.name
            if name == 'playwriter':
                executable = shutil.which('node')
                command = [executable or 'node', str(ROOT / 'tools/playwriter/node_modules/playwriter/bin.js')]
                if not executable or not Path(command[1]).is_file():
                    raise RuntimeError('Run setup playwriter first')
                os.environ.update(PLAYWRITER_TELEMETRY='0', DO_NOT_TRACK='1')
            elif name == 'vibetest':
                command = [str(python_for(name)), str(ROOT / 'tools/vibetest_mcp.py')]
            else:
                command = [sys.executable, str(ROOT / 'tools/container_use.py'), 'stdio']
            os.chdir(ROOT)
            os.execv(command[0], command)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'Tool could not run: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
