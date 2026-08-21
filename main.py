import json
from core.utils import read_json, write_json
from pathlib import Path

from core.path import ProjectPaths
from core.utils import safe_filename
from pipeline.pipeline import AutoVideoPipeline


def main():

    jobs = read_json(ProjectPaths().task_file)
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
