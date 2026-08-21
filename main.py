import json
from pathlib import Path

from core.path import ProjectPaths
from core.utils import safe_filename
from pipeline.pipeline import AutoVideoPipeline


def main():

    with open(ProjectPaths().task_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"📦 Total jobs: {len(jobs)}")

    for i, job in enumerate(jobs):
        job_name = safe_filename(job.get("subtitle") or job["title"])
        project_paths = ProjectPaths(Path("work") / f"{i + 1:03d}_{job_name}")
        print(f"\n▶ Job {i+1}/{len(jobs)}")
        AutoVideoPipeline(project_paths).run(
            urls=job["urls"],
            title=job["title"],
            subtitle=job.get("subtitle"),
            upload=True,
        )

    print("\n🎬 ALL DONE")

    


if __name__ == "__main__":
    main()
