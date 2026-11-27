import argparse
import hashlib
import traceback
from pathlib import Path

from core.path import ProjectPaths
from core.utils import safe_filename
from pipeline.source_preprocess import download_raw_video, load_json, probe_source, save_json, validate_profile


def load_batch(path):
    jobs = load_json(path)
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("任务列表不能为空")
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("title"), str) or not job["title"].strip():
            raise ValueError("每个任务必须有非空剧名 title")
        if type(job.get('episode')) is not int or job['episode'] < 1:
            raise ValueError("每个任务必须有正整数 episode（集数），例如 episode: 1")
        urls = job.get("urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not urls or any(not isinstance(u, str) or not u.strip() for u in urls):
            raise ValueError("每个任务必须有有效的 urls")
    titles = {job["title"].strip() for job in jobs}
    if len(titles) != 1:
        raise ValueError("一次批处理只能包含同一部电视剧；请将不同电视剧分开配置")
    if len({job['episode'] for job in jobs}) != len(jobs):
        raise ValueError("同批任务的 episode 不能重复")
    return jobs, titles.pop()


def batch_profile_path(title):
    suffix = hashlib.sha256(title.encode()).hexdigest()[:10]
    return Path("work/preprocess_profiles")/f"{safe_filename(title)[:60]}_{suffix}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="同剧整批选区、生成整集母版并制作解说")
    parser.add_argument("--tasks", type=Path, default=Path("tasks.json"))
    parser.add_argument("--edit-preprocess", action="store_true", help="重新打开整批选区工具")
    parser.add_argument("--configure-only", action="store_true", help="只保存配置，不运行生产或上传")
    parser.add_argument("--preview-source", type=Path, help="使用本地视频选区，省去参考素材下载")
    parser.add_argument("--profile", type=Path, help="指定整批预处理配置文件")
    args = parser.parse_args(argv)
    jobs, title = load_batch(args.tasks)
    profile_path = args.profile or batch_profile_path(title)
    profile = load_json(profile_path) if profile_path.exists() else None
    if profile is not None:
        validate_profile(profile, title)
    if profile is None or args.edit_preprocess or args.configure_only:
        from pipeline.preprocess_ui import choose_profile
        first_urls = jobs[0]["urls"]
        reference = args.preview_source or download_raw_video(
            first_urls if isinstance(first_urls, str) else first_urls[0])
        probe_source(reference)
        profile = choose_profile(reference, title, profile_path, initial=profile,
                                 batch_count=len(jobs), configure_only=args.configure_only)
        if profile is None:
            print("本批任务已取消，未开始处理。")
            return 0
    print(f"整批共 {len(jobs)} 集，使用配置: {profile_path}", flush=True)
    if args.configure_only:
        print("配置已保存。本次没有启动生产或上传。")
        return 0

    from pipeline.pipeline import AutoVideoPipeline
    results = []
    for index, job in enumerate(jobs, 1):
        name = f"第{job['episode']}集"
        paths = ProjectPaths(Path('work')/safe_filename(title)/f"第{job['episode']:03d}集")
        print(f"\n▶ {index}/{len(jobs)}: {name}", flush=True)
        try:
            AutoVideoPipeline(paths).run(
                urls=job["urls"], title=title, episode=job['episode'], upload=True,
                preprocess_profile=profile,
                background_music=job.get("background_music") or job.get("背景音乐"),
                background_music_volume=(job.get("background_music_volume")
                    if job.get("background_music_volume") is not None else job.get("背景音乐音量")),
            )
            results.append({"episode": job['episode'], "status": "completed"})
        except Exception as error:
            traceback.print_exc()
            print(f"[FAILED] {name}: {error}；继续下一集", flush=True)
            results.append({"episode": job['episode'], "status": "failed", "error": str(error)})
        save_json(Path("work/main_batch_result.json"), {"drama_title": title,
                  "profile_path": str(profile_path), "results": results})
    failed = sum(r["status"] == "failed" for r in results)
    print(f"\n整批结束：完成 {len(results)-failed} 集，失败 {failed} 集。详情: work/main_batch_result.json")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
