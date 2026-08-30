"""PC Diagnostic Agent — unified entry point.

When run with arguments this behaves as the technician CLI.  When run with no
arguments (as the Windows Service Control Manager does) it hands control to the
pywin32 service dispatcher.

Usage:
    pcdiag status               # technician CLI
    pcdiag simulate-incident --type hard-hang   # safe synthetic-data harness
    pcdiag service install      # install the Windows service
"""

import sys


def main() -> int:
    if len(sys.argv) <= 1:
        # SCM launches the service executable without arguments; pywin32's
        # HandleCommandLine detects the service context (or prints usage when
        # run interactively).
        from service.windows_service import run_service_command_line

        run_service_command_line()
        return 0

    from cli.commands import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
