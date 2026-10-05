from pathlib import Path

JOBS = sorted(Path(__file__).parent.parent.joinpath("jobs").glob("*.sql"))


def main() -> None:
    for job in JOBS:
        print(job.name)
