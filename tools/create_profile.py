#!/usr/bin/env python3
"""CLI tool: create a Pure-Trace patient profile."""
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pure_trace.data_layer import ProfileManager


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python tools/create_profile.py "Nome Cognome" [alias]')
        print('  Il nome viene cifrato. L\'alias e\' l\'etichetta in chiaro che')
        print('  compare nel selettore prima della password (default: iniziali).')
        sys.exit(1)

    name = sys.argv[1].strip()
    if not name:
        print("Error: name cannot be empty")
        sys.exit(1)

    pm = ProfileManager()
    alias = sys.argv[2].strip() if len(sys.argv) > 2 else pm.default_alias(name)

    password = getpass.getpass("Password (min 8 characters): ")
    if len(password) < 8:
        print("Error: password must be at least 8 characters")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match")
        sys.exit(1)

    profile = pm.create_profile(name, password, alias=alias)
    print(f"Profile created: {profile.dir}")
    print(f"Alias visibile senza password: {profile.alias!r}")


if __name__ == "__main__":
    main()
