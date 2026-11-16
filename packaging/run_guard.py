"""PyInstaller entry: absolute import so the frozen app has package context."""
from pilayer.cli import main

raise SystemExit(main())