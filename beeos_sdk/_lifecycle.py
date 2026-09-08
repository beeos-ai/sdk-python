"""Cleanup for owned generated clients across generator versions."""


def close_api_client(api_client) -> None:
    close = getattr(api_client, "close", None)
    if callable(close):
        close()
        return
    # The current synchronous generator has a no-op __exit__ and no close().
    # Clear its urllib3 pools rather than pretending the facade released them.
    rest = getattr(api_client, "rest_client", None)
    pool = getattr(rest, "pool_manager", None)
    clear = getattr(pool, "clear", None)
    if callable(clear):
        clear()
