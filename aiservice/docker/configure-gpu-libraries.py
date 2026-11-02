"""Expose wheel-provided NVIDIA libraries to CTranslate2's native loader."""

import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

ERROR_CODE = "SS-DEP-0001"
LIBRARIES = {
    "libcublas.so.12": "cublasCreate_v2",
    "libcublasLt.so.12": "cublasLtCreate",
    "libcudnn.so.9": "cudnnGetVersion",
    "libcudnn_ops.so.9": "cudnnCreateTensorDescriptor",
}


def library_directories():
    directories = set()
    for key in ("purelib", "platlib"):
        root = Path(sysconfig.get_path(key))
        directories.update(path.resolve() for path in root.glob("nvidia/*/lib") if path.is_dir())
        torch_lib = root / "torch" / "lib"
        if torch_lib.is_dir():
            directories.add(torch_lib.resolve())
    return sorted(directories)


def configure(destination=Path("/etc/ld.so.conf.d/asr-nvidia.conf")):
    directories = library_directories()
    if not directories:
        raise RuntimeError("No NVIDIA wheel libraries found; rebuild with Dockerfile.gpu")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write("".join(f"{path}\n" for path in directories))
        temporary.chmod(0o644)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    subprocess.run(["ldconfig"], check=True)


def check_libraries():
    # Resolve by SONAME in a fresh process, without torch preloading dependencies.
    for name, symbol in LIBRARIES.items():
        library = ctypes.CDLL(name)
        getattr(library, symbol)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check native loading without writing config"
    )
    arguments = parser.parse_args()
    try:
        if arguments.check:
            check_libraries()
        else:
            configure()
            subprocess.run([sys.executable, __file__, "--check"], check=True)
    except (OSError, AttributeError, RuntimeError, subprocess.SubprocessError) as exc:
        print(
            f"{ERROR_CODE}: CUDA library setup failed ({exc}). "
            "Rebuild Dockerfile.gpu and run configure-gpu-libraries.py --check; "
            "see README.md GPU troubleshooting.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
