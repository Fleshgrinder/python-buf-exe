<div align="center">
  <h1>
    <img src="https://raw.githubusercontent.com/Fleshgrinder/python-buf-exe/main/.idea/icon.svg" height="40" width="40" alt="Protobuf Logo"><br>
    Python Buf Executable
  </h1>
  <p><b>PyPI packaged Buf CLI</b></p>
</div>

A PyPI package providing a pip-installable [buf] executable.

This package does not provide any Python code, it provides just the unaltered
`buf` executable.

If you want to use `buf` for code generation you might also want to check out
[protoc-exe].

> **Note** that this project is not affiliated with or endorsed by Buf
> Technologies. The `-exe` suffix in the name was chosen to ensure that the
> `buf` name stays available, just in case there ever is going to be an official
> package.

> **Warning** the redistribution process is not yet fully automated, as I am in
> the process of building the tooling. Currently only the latest `buf` release
> is available, and it was created semi-manually with the scripts you currently
> see in the repository. The plan is to fully automate everything, and provide
> new `buf` releases with 24 hours.

## Usage

Simply use `buf` as the executable in whatever process abstraction you are
using, regardless of your operating system. The only requirement is that your
`PATH` is set correctly so that the `buf` (or `buf.exe` on Windows) is found.
For instance, you could use `pip` and a basic virtual environment:

```python
# example.py
import subprocess
subprocess.check_call(["command", "-v", "buf"])
subprocess.check_call(["buf", "--version"])
```

```shell
cd /tmp
python -m venv venv
source venv/bin/activate
pip install buf-exe
command -v buf # /tmp/venv/bin/buf
buf --version  # x.y.z
python example.py
# /tmp/venv/bin/buf
# x.y.z
rm -fr venv/
```

> **Note** that the example uses a POSIX compliant shell, but it works on
> non-POSIX systems as well. Have a look at the GitHub Actions.

[buf]: https://buf.build/
[protoc-exe]: https://github.com/fleshgrinder/python-protoc-exe
