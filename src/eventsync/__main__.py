import uvicorn

from eventsync.config import DEFAULT


def main() -> None:
    uvicorn.run("eventsync.api.app:app", host=DEFAULT.host, port=DEFAULT.port)


if __name__ == "__main__":
    main()
