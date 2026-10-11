"""
A plain `Path.write_text()` truncates before writing the new content,
so a concurrent reader can see an empty or partial file mid-write --
confirmed separately to hit this on over half of reads under real
concurrent load, which is what let `ensure_daemon()` repeatedly
mistake a live daemon for a dead one and spawn a duplicate. `write_atomic`
must never expose that window, for both an existing and a brand-new path.
"""
import multiprocessing as mp
import time

from owrap.utils.io.atomic import write_atomic


def _writer(path, deadline):
    while time.time() < deadline:
        write_atomic(path, "222")
        write_atomic(path, "111")


def _reader(path, deadline, results):
    bad = 0
    while time.time() < deadline:
        raw = path.read_text().strip()
        try:
            int(raw)
        except ValueError:
            bad += 1
    results.append(bad)


def test_write_atomic_never_exposes_a_torn_read(tmp_path):
    path = tmp_path / "daemon.pid"
    write_atomic(path, "111")
    deadline = time.time() + 1.0

    manager = mp.Manager()
    results = manager.list()
    writer = mp.Process(target=_writer, args=(path, deadline))
    reader = mp.Process(target=_reader, args=(path, deadline, results))
    writer.start()
    reader.start()
    writer.join()
    reader.join()

    assert list(results) == [0]


def test_write_atomic_creates_a_brand_new_file(tmp_path):
    path = tmp_path / "new_file.pid"

    write_atomic(path, "42")

    assert path.read_text() == "42"
