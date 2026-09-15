import time


def monotonic_milliseconds() -> int:
    return time.monotonic_ns() // 1_000_000


def main():
    print(monotonic_milliseconds())


if __name__ == "__main__":
    main()
