"""PyInstaller launcher for LiveChat Guard.

Build using build_release.bat; do not invoke the package __main__.py
as a standalone path because it contains a relative import.
"""
from multiprocessing import freeze_support


def main():
    freeze_support()
    from livechat_guard.gui import main as gui_main
    gui_main()


if __name__ == '__main__':
    main()
