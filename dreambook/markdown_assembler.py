#!/usr/bin/env python3
"""DreamBook Markdown 装配器 — 把图 + 故事拼成 markdown 绘本

输出结构：
  run_dir/
  ├── 绘本.md              ← 主文件（用相对路径引用图片）
  ├── images/
  │   └── page_01.png ~ page_06.png
  └── 绘本.zip             ← 打包（用户下载用）

这样 markdown 预览器（含浏览器 marked.js）能直接渲染图文，
用户下载 zip 解压后用任何 markdown 编辑器都能看。
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


def assemble_markdown(story: dict, image_dir: Path, run_dir: Path) -> Path:
    """
    story: { title, dream, pages: [{page, scene_description, story_text}] }
    image_dir: 存放 page_01.png 等图片的目录
    run_dir: 输出根目录（绘本.md 和 images/ 都放在这里）
    """
    title = story.get("title", "我的梦想绘本")
    dream = story.get("dream", "")
    pages = story.get("pages", [])

    # 1) 把图片复制到 run_dir/images/（统一位置 + 用相对路径）
    md_images_dir = run_dir / "images"
    md_images_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    for i, page in enumerate(pages, 1):
        src = image_dir / f"page_{i:02d}.png"
        if src.exists():
            dst = md_images_dir / f"page_{i:02d}.png"
            shutil.copy2(src, dst)
            image_paths.append(f"images/page_{i:02d}.png")
        else:
            image_paths.append(None)

    # 2) 生成 markdown
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    if dream:
        lines.append(f"> {dream}")
        lines.append("")
    lines.append("---")
    lines.append("")

    for i, page in enumerate(pages, 1):
        text = page.get("story_text", "")
        img_rel = image_paths[i - 1] if i - 1 < len(image_paths) else None

        if img_rel:
            lines.append(f"![第 {i} 页 · {title}]({img_rel})")
            lines.append("")
        lines.append(f"**第 {i} 页**")
        lines.append("")
        if text:
            lines.append(text)
        else:
            lines.append("（这一页留白，等你来填）")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 封底
    lines.append("## 🌟")
    lines.append("")
    lines.append("*梦想这条路，一旦开始走，就已经在实现。*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"<sub>由 DreamBook 在 DGX Spark 上生成 · {len(pages)} 页绘本</sub>")
    lines.append("")

    md_path = run_dir / f"{title}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # 3) 打包 zip
    zip_path = run_dir / f"{title}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 加 markdown
        zf.write(md_path, f"{title}.md")
        # 加图片
        for img in md_images_dir.iterdir():
            zf.write(img, f"images/{img.name}")
        # 加一个 README
        readme = (
            f"# {title}\n\n"
            f"打开 `{title}.md` 查看绘本。\n"
            f"图片在 `images/` 文件夹里。\n\n"
            f"用任何 Markdown 编辑器（Typora / VSCode / Obsidian）打开效果最佳。\n"
        )
        zf.writestr("README.txt", readme)

    return md_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story-json", required=True)
    ap.add_argument("--image-dir", required=True, help="图片所在目录")
    ap.add_argument("--run-dir", required=True, help="输出根目录")
    args = ap.parse_args()

    story = json.loads(Path(args.story_json).read_text(encoding="utf-8"))
    md = assemble_markdown(
        story,
        Path(args.image_dir),
        Path(args.run_dir),
    )
    print(f"MD_OK:{md}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
