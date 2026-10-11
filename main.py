"""
RL PCB - AI Copilot for KiCad
Standalone runner and entrypoint.
"""
import sys
from rlpcb.cli import main

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print("=" * 60)
        print("RL PCB: AI Copilot for KiCad (schematic, routing, verification)")
        print("Usage: python main.py <command> [options]")
        print("Try:   python main.py doctor")
        print("=" * 60)
        sys.exit(main(["doctor"]))
    sys.exit(main(sys.argv[1:]))
