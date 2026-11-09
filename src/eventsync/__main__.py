import os

import uvicorn

from eventsync.config import DEFAULT


def main() -> None:
    """Start the API. PORT / HOST environment variables override the defaults."""
    host = os.environ.get("HOST", DEFAULT.host)
    port = int(os.environ.get("PORT", DEFAULT.port))
    uvicorn.run("eventsync.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
