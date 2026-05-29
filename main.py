import json

from core.path import ProjectPaths

from core.utils import clear_workdir
from pipeline.pipeline import AutoVideoPipeline


def main():

    with open(ProjectPaths().task_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"📦 Total jobs: {len(jobs)}")

    for i, job in enumerate(jobs):
        clear_workdir(ProjectPaths().root)
        print(f"\n▶ Job {i+1}/{len(jobs)}")
        AutoVideoPipeline().run(url=job["url"], title=job["title"], upload = True)

    print("\n🎬 ALL DONE")

    


if __name__ == "__main__":
    main()