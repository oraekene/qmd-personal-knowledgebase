"""Entry point for `python -m auth_proxy` — thin wrapper over server.main (fixes Divergent Change)."""

from auth_proxy.server import main

if __name__ == "__main__":
    main()
