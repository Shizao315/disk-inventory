"""Assemble the bounded test release and record executable/source provenance."""
from pathlib import Path
import datetime
import hashlib
import json
import struct
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
parser = argparse.ArgumentParser()
parser.add_argument('--archive-name', default='DiskInventory-0.1.0-test-win64.zip')
args = parser.parse_args()
if Path(args.archive_name).name != args.archive_name or not args.archive_name.endswith('.zip'):
    parser.error('archive-name must be a ZIP file name, without directories')
exe = DIST / 'DiskInventory.exe'
binary = exe.read_bytes()
pe = struct.unpack_from('<I', binary, 60)[0]
assert binary[pe:pe+4] == b'PE\0\0'
opt = pe + 24
assert struct.unpack_from('<H', binary, pe+4)[0] == 0x8664
assert struct.unpack_from('<H', binary, opt+68)[0] == 2
sections = []
count = struct.unpack_from('<H', binary, pe+6)[0]
start = opt + struct.unpack_from('<H', binary, pe+20)[0]
for i in range(count):
    sec = start+i*40
    virtual_size, address, size, offset = struct.unpack_from('<IIII', binary, sec+8)
    sections.append((address, max(virtual_size, size), offset))


def file_offset(rva):
    for address, size, offset in sections:
        if address <= rva < address+size:
            return offset+rva-address
    raise ValueError(f'Invalid PE RVA {rva:x}')


imports = []
pos = file_offset(struct.unpack_from('<I', binary, opt+120)[0])
while any(binary[pos:pos+20]):
    name = file_offset(struct.unpack_from('<I', binary, pos+12)[0])
    imports.append(binary[name:binary.index(0, name)].decode('ascii'))
    pos += 20
system = {'kernel32.dll', 'user32.dll', 'gdi32.dll', 'shell32.dll', 'ole32.dll', 'comdlg32.dll', 'advapi32.dll', 'msvcrt.dll', 'ntdll.dll'}
assert all(x.lower() in system or (x.lower().startswith('api-ms-win-crt-') and x.lower().endswith('.dll')) for x in imports), imports
checks = json.loads((ROOT / 'test-output/integration-results.json').read_text())
browser = json.loads((ROOT / 'test-output/browser-results.json').read_text())
digest = hashlib.sha256(binary).hexdigest()
assert checks['exe_sha256'] == digest
assert browser['status'] == 'PASS'
assert browser['template_sha256'] == hashlib.sha256((ROOT / 'src/report-template.html').read_bytes()).hexdigest()
source_files = ['src/main.cpp', 'src/report-template.html', 'build.ps1', 'setup-toolchain.ps1', 'tests/integration.py', 'tests/report-browser.cjs', 'tests/run-browser.ps1', 'tools/package.py', '.github/workflows/windows.yml', 'README.md', 'SPEC.md', 'SIGNING.md', 'VALIDATION.md', 'downloads/README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.txt']
manifest = {
    'version': '0.1.0-test',
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'exe': {'name': exe.name, 'bytes': len(binary), 'sha256': digest, 'machine': 'x86_64', 'subsystem': 'Windows GUI', 'imports': imports},
    'toolchain': json.loads((ROOT / '.tools/toolchain.json').read_text(encoding='utf-8-sig')),
    'sources_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_files},
    'integration': checks,
    'execution_status': 'NOT_PASSED' if checks['status'] != 'PASS' else 'PASS',
    'prior_native_validation': {'sha256': 'd68fdc9dc70309ccbc7fc94a24c5f1b3fb86a3d4b903ff53361d64a5db98b5e2', 'tests_passed': 8, 'time_local': '2026-11-08 13:32', 'evidence': 'Historical local verification documented in VALIDATION.md; not proof of final binary execution.'},
    'browser': browser,
    'not_validated': ['full-volume elevated MFT runtime and performance', 'million-record real-world report', 'Windows machines other than this test host', 'all cloud-provider placeholder cases'],
}
(DIST / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
(DIST / 'SHA256SUMS.txt').write_text(digest+'  DiskInventory.exe\n', encoding='ascii')
archive = DIST / args.archive_name
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for item in [exe, ROOT / 'README.md', ROOT / 'LICENSE', ROOT / 'THIRD_PARTY_NOTICES.txt', ROOT / 'SIGNING.md', ROOT / 'VALIDATION.md', DIST / 'manifest.json', DIST / 'SHA256SUMS.txt']:
        z.write(item, item.name)
print(json.dumps({'exe_bytes': len(binary), 'exe_sha256': digest, 'imports': imports, 'zip_bytes': archive.stat().st_size}, indent=2))
