# 天龙八部三版本地下载 / GitHub Actions 无 Drive 授权通道

**现状**：OSR 现有 `acquisition/bulk_watcher.py` 只枚举 Hugging Face `targets.json`，并没有执行 `control/*.json` 的通用指令调度器。因此仅创建 GitHub issue/控制文件不能证明 Mac 已接单。

**这次真正发给 GitHub Actions 的任务**：`.github/workflows/tianlong-analyze-no-drive.yml`。每次工作流文件推送到 master 或手动 Dispatch 会执行三版拉取与人物/武功的启发式统计。由于仓库公开，Actions 只上传无全文、无连续原文锚点的统计汇总：manifest.json、chapter_scan.csv、person_skill_matrix.csv、SOURCE_COMMIT.txt。**不上传小说正文**。

## Mac 本地一键执行

如果 OSR 代码已经在 `~/Open-Source-Research-OSR-`：

```bash
git -C "$HOME/Open-Source-Research-OSR-" pull --ff-only origin master
zsh "$HOME/Open-Source-Research-OSR-/acquisition/download_tianlong_local.sh"
```

如果尚未 clone：

```bash
git clone https://github.com/rayzh2012/Open-Source-Research-OSR-.git "$HOME/Open-Source-Research-OSR-"
zsh "$HOME/Open-Source-Research-OSR-/acquisition/download_tianlong_local.sh"
```

可自定义目录，例如：`zsh "$HOME/Open-Source-Research-OSR-/acquisition/download_tianlong_local.sh" "$HOME/Downloads/天龙八部_三版本"`。

Mac 默认路径 `~/Documents/金庸研究/天龙八部_三版本/`，下有 `JY_upstream/`（Git sparse checkout 原始三版 Markdown）和 `研究产出/Markdown`、`研究产出/ZIP`、`研究产出/INDEX`、`研究产出/ANALYSIS`。本地下载脚本不调用 Google Drive，也不需要授权。

## Notion 收纳原则

只把原文 GitHub 链接、章节定位、版本差异、算法摘要、来源 commit 和 TODO 写入已存在的 `REF｜金庸原报·三版文本·GitHub武功Excel数据库｜SOURCE INDEX` 及 `INDEX｜旧版失落武功·降龙十八掌传承·版本删改｜CURRENT`；不把三版本整本版权文本复制进 Notion。

## 使用限制

- GitHub 原仓库是第三方转录文本，未获逐字核实《明报》报纸连载。
- 三版书的章节号不同，算法候选匹配不等于已证明是同一剧情或实际使出了该武功。
- GitHub Actions 的下载只发生在临时 Runner；要把全文保存在 Mac，必须这台 Mac 的脚本实际执行。没有远程 Mac 执行工具时，无法从当前聊天代运行 Mac 下载。