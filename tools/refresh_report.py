"""Apply the trusted current UI to an existing report without rescanning files."""
from __future__ import annotations

import argparse
import hashlib
import mmap
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = b'<script id="scan-data" type="application/json">'


def refresh_report(source, output=None):
    source = Path(source).absolute()
    template = (ROOT / 'src' / 'report-template.html').read_bytes()
    if template.count(b'<!--DISK_DATA-->') != 1:
        raise ValueError('Invalid trusted report template')
    info = source.stat()
    token = hashlib.sha256(template + str((str(source), info.st_size, info.st_mtime_ns)).encode()).hexdigest()[:12]
    destination = Path(output).absolute() if output else source.with_name(source.stem + '-ui-' + token + '.html')
    if os.path.normcase(str(source)) == os.path.normcase(str(destination)):
        raise ValueError('Keep the original report; choose another output name')
    if destination.exists():
        if output:
            raise FileExistsError(str(destination))
        return destination
    head, tail = template.split(b'<!--DISK_DATA-->')
    temporary = Path(str(destination) + '.tmp')
    with source.open('rb') as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        start = mapped.find(MARKER)
        if start < 0:
            raise ValueError('No DiskInventory data payload in this HTML')
        start += len(MARKER)
        end = mapped.find(b'</script>', start)
        if end < 0:
            raise ValueError('Incomplete report payload')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open('xb') as target:
            target.write(head)
            for offset in range(start, end, 1024 * 1024):
                # Only the JSON data crosses into the new report, never old
                # scripts. Escape HTML delimiters without loading all records.
                block = mapped[offset:min(end, offset + 1024 * 1024)]
                target.write(block.replace(b'<', b'\\u003c').replace(b'>', b'\\u003e').replace(b'&', b'\\u0026'))
            target.write(tail)
            target.flush()
            os.fsync(target.fileno())
        after = source.stat()
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Source report changed while upgrading; temporary copy preserved')
    os.rename(temporary, destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('--output')
    args = parser.parse_args()
    print(refresh_report(args.report, args.output))
