"""Project-local installer and MCP launcher for container-use v0.4.2."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v0.4.2'
# Digests published by dagger/container-use for this release.
DIGESTS = {
    ('linux', 'amd64'): '3fa52b5833ae4aed2be4b86f7cf42671fdf4bca8c211fe5fff08cc19553d409b',
    ('linux', 'arm64'): '96db6bc01111c573df83065bd02802a36a09864f45373169ffa227a9b3cdca14',
    ('darwin', 'amd64'): '7bdfef614c1d3dad6675efb894d854f0c1f7d56fbac2a1662e96fd9a5177821b',
    ('darwin', 'arm64'): '9ae2ca3ead64e9d9780e5a017704d4d053d1b9af7dadfb19b84eec5e968deffb',
    ('windows', 'amd64'): 'a5fe8bb0022cce8e65c28a0c8dff6aba3b8edcce5d0f1e955de3c24fffd5e438',
    ('windows', 'arm64'): 'adbc71aded86459f5a08ffc86638388f7f5cb0ea1c109d8accdc1cde8f415571',
}
BINARY = ROOT / '.tools' / ('container-use.exe' if os.name == 'nt' else 'container-use')


def extract_verified(archive, expected, target):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError('SHA-256 mismatch: downloaded archive was not installed')
    with tarfile.open(archive, 'r:gz') as bundle:
        name = 'container-use.exe' if target.suffix == '.exe' else 'container-use'
        member = bundle.getmember(name)
        if not member.isfile():
            raise ValueError('Archive binary is not a regular file')
        binary = bundle.extractfile(member).read()
        license_text = bundle.extractfile('LICENSE').read()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.installing')
    temporary.write_bytes(binary)
    temporary.chmod(0o755)
    temporary.replace(target)
    (target.parent / 'container-use-LICENSE').write_bytes(license_text)


def install():
    system = platform.system().lower()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    digest = DIGESTS.get((system, arch))
    if not digest:
        raise ValueError('Unsupported platform; use a supported Linux/WSL2, macOS or Windows host')
    asset = f'container-use_{VERSION}_{system}_{arch}.tar.gz'
    url = f'https://github.com/dagger/container-use/releases/download/{VERSION}/{asset}'
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / asset
        with urllib.request.urlopen(url, timeout=120) as response:
            archive.write_bytes(response.read())
        extract_verified(archive, digest, BINARY)
    print(f'Installed {BINARY}')


def doctor():
    binary = BINARY.is_file()
    if binary:
        subprocess.run([str(BINARY), 'version'], check=True, cwd=ROOT, timeout=30)
    docker = shutil.which('docker')
    ready = False
    if docker:
        ready = subprocess.run([docker, 'info'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    print(json.dumps({'container_use_installed': binary, 'docker_ready': ready,
                      'container_test_executed': False}, indent=2))
    return 0 if binary and ready else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'doctor', 'stdio', 'mcp-config'])
    args = parser.parse_args()
    if args.command == 'install':
        install()
    elif args.command == 'doctor':
        return doctor()
    elif args.command == 'mcp-config':
        print(json.dumps({'mcpServers': {'container-use': {'command': sys.executable,
                             'args': [str(Path(__file__).resolve()), 'stdio']}}}, indent=2))
    else:
        if not BINARY.is_file():
            parser.error('Run python tools/container_use.py install first')
        os.chdir(ROOT)
        os.execv(str(BINARY), [str(BINARY), 'stdio'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
