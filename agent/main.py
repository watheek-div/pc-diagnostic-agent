"""Foreground entry point for the agent.

Used for development/debugging and as the work function invoked by the Windows
service.  Runs startup analysis then the scheduler + watchdog loop until a stop
event is set.
"""

from __future__ import annotations

import threading

from agent.config import Config, load_config
from agent.lifecycle import Agent


def run_agent(config: Config | None = None, stop_event: threading.Event | None = None) -> None:
    cfg = config or load_config()
    stop_event = stop_event or threading.Event()
    agent = Agent(cfg)
    agent.initialize()
    agent.startup_analysis()
    agent.run(stop_event)


if __name__ == "__main__":
    run_agent()
