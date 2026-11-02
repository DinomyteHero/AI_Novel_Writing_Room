#!/bin/sh
# Double-click to start the Writers Room on a Mac. On Linux, run it from a
# terminal: ./"Start Writers Room.command"
# The first run sets up a private copy of what the app needs in .venv, so
# nothing is installed into your system Python. Later runs start straight away.
# Anything after the name goes to the app, such as --port 9000.

cd "$(dirname "$0")" || exit 1

stopped() {
    printf '\nPress Return to close this window.'
    read -r _
    exit 1
}

version_ok='import sys; sys.exit(sys.version_info < (3, 10))'
venv_python=.venv/bin/python

# A .venv copied from another computer or left by a removed Python won't run.
if ! { [ -x "$venv_python" ] && "$venv_python" -c "" >/dev/null 2>&1; }; then
    rm -rf .venv
    python=""
    for candidate in python3 python; do
        if "$candidate" -c "$version_ok" >/dev/null 2>&1; then
            python=$candidate
            break
        fi
    done
    if [ -z "$python" ]; then
        echo "The Writers Room needs Python 3.10 or newer, and this computer doesn't have it yet."
        echo "Install it from https://www.python.org/downloads/ and run this file again."
        command -v open >/dev/null 2>&1 && open "https://www.python.org/downloads/"
        stopped
    fi
    echo "Setting up the Writers Room. This happens once and takes a minute or two."
    if ! "$python" -m venv .venv; then
        echo
        echo "Couldn't set up. On Debian or Ubuntu, install python3-venv and run this file again."
        stopped
    fi
fi

if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
    echo "Installing what the app needs..."
    if ! "$venv_python" -m pip install --quiet --disable-pip-version-check -r requirements.txt; then
        echo
        echo "Setup didn't finish; see the message above. It usually means the internet"
        echo "connection dropped. Run this file again to try again."
        stopped
    fi
    cp requirements.txt .venv/installed-requirements.txt
fi

"$venv_python" scripts/app.py "$@" || stopped
