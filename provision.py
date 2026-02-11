#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "space" / "space-os"))

from space.ledger import projects

def main():
    if len(sys.argv) != 3:
        print("usage: provision.py <name> <repo_path>", file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    repo_path = sys.argv[2]
    
    project = projects.create(name, repo_path)
    print(project.id)

if __name__ == "__main__":
    main()
