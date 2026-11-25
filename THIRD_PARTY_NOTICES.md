# Third-party software

SomaWave’s Python wheel and Linux archive contain SomaWave source, assets, and installation files. The installer obtains Python dependencies as separate distributions. It uses the system’s Python and MPV. The packages contain no MPV, FFmpeg, Python runtime, terminal emulator, or copies of SomaFM programming.

## Python runtime dependencies

The versions below are the dependency set checked for the release. Each dependency retains its upstream license and notices. The table describes the distributions installed by pip in the virtual environment.

| Distribution | Version checked | License |
| --- | --- | --- |
| [Textual](https://pypi.org/project/textual/8.2.8/) | 8.2.8 | MIT |
| [Rich](https://pypi.org/project/rich/15.0.0/) | 15.0.0 | MIT |
| [markdown-it-py](https://pypi.org/project/markdown-it-py/4.3.0/) | 4.3.0 | MIT, with upstream markdown-it license notice |
| [mdit-py-plugins](https://pypi.org/project/mdit-py-plugins/0.7.0/) | 0.7.0 | MIT |
| [linkify-it-py](https://pypi.org/project/linkify-it-py/2.2.0/) | 2.2.0 | MIT |
| [mdurl](https://pypi.org/project/mdurl/0.1.2/) | 0.1.2 | MIT |
| [platformdirs](https://pypi.org/project/platformdirs/4.14.8/) | 4.14.8 | MIT |
| [Pygments](https://pypi.org/project/Pygments/2.21.0/) | 2.21.0 | BSD-2-Clause |
| [typing-extensions](https://pypi.org/project/typing-extensions/4.16.0/) | 4.16.0 | PSF-2.0 |

Setuptools builds the project in an isolated environment and is MIT-licensed. The checked setuptools wheel (84.2.1) includes vendored components with their own notices, including autocommand under LGPLv3, importlib-metadata under Apache-2.0, and packaging under Apache-2.0 or BSD-2-Clause. Its other vendored components in that wheel use MIT. Build and validation tools are separate from the runtime payload. Python dependency versions can vary within the package requirements. Preserve the upstream notices of the selected versions if redistributing a virtual environment or dependency bundle.

## System software and data

- Python is provided by the host distribution under the Python Software Foundation license and accompanying notices. [Python licensing](https://docs.python.org/3/license.html)
- SomaWave starts MPV as an external process and controls it through its documented JSON IPC interface. MPV is available in GPL and LGPL build configurations. Its FFmpeg libraries may also be subject to LGPL or GPL terms depending on build options. The host distribution supplies these binaries and their notices. Bundling those binaries would require a separate compliance review for the exact builds and linked libraries. [MPV copyright and licensing](https://github.com/mpv-player/mpv/blob/master/Copyright) · [FFmpeg licensing](https://ffmpeg.org/legal.html)
- Omarchy launcher tools and system terminal dispatch are optional external programs. Their files and settings stay with the host system.
- SomaFM supplies the station directory and streams. This project’s software license does not cover SomaFM’s data, programming or marks. [SomaFM](https://somafm.com/)
