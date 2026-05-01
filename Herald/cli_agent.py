#!/usr/bin/env python3
"""Compatibility entrypoint for the structured Herald CLI agent."""

from herald_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
