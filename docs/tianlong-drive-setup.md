# 《天龙八部》旧版／三联版／新修版 → Google Drive

本工作流只备份《天龙八部》三个版本，不将任何小说正文提交到本公开 GitHub 仓库。完整 Markdown、分版 ZIP、SHA256 校验表、来源 commit 和算法比对表仅进入你指定的私人 Google Drive。

- **来源**：公开第三方转录仓库 [OliverCWY/JY](https://github.com/OliverCWY/JY) 下 `Markdown/{旧版,三联版,新修版}/天龙八部/`。第三方整理≠《明报》原报逐字校勘。
- **目标**：Google Drive 现有 `20_Creative Writing & History/金庸MOD` 文件夹，下设 `天龙八部_三版本/`，不删除其中其他文件。
- **触发方式**：GitHub Actions → **天龙八部：三版本全文 → 私人 Google Drive** → **Run workflow**。
- **归档结构**：`Markdown/{旧版,三联版,新修版}/天龙八部/*.md`；`ZIP/天龙八部_{版}_Markdown.zip`；`INDEX/manifest.json`、`INDEX/sha256.csv`；可选 `ANALYSIS/*.csv`。
- **同步**：`rclone copy --checksum`，不是 `sync`。重复运行只增量更新，不删除 Drive 文件。

## 必须进行一次的授权（不要把 token 发到聊天）

1. 在自己计算机安装 [rclone](https://rclone.org/install/)，运行 `rclone config`，选择 `n` 新建 remote，名称输入 **`gdrive`**，Storage 选 Google Drive，然后完成浏览器中的 Google 登录和授权。
2. 找到自己本地的 `rclone.conf` 配置文件（`rclone config file` 会显示路径），确保存在 `[gdrive]` 区块。
3. 把 **整个配置文件**（含刷新令牌）进行 Base64 编码，并 **只**存入 GitHub 仓库的 Actions secret `GDRIVE_RCLONE_CONFIG_B64`：
   - macOS：`base64 < "$(rclone config file | tail -1)" | tr -d '\n'`
   - Linux：`base64 -w0 "$(rclone config file | tail -1)"`
   - Windows PowerShell：`[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:APPDATA\rclone\rclone.conf"))`
4. 把目标 **金庸MOD 文件夹的 Google Drive folder ID** 填入另一个 Actions secret `GDRIVE_FOLDER_ID`（只填 ID，不是完整 URL）。
5. 打开 GitHub 仓库 **Settings → Secrets and variables → Actions → New repository secret**，保存以上两项。使用本人 Google 账号登录；不要将凭证、刷新 token 或 Base64 字符串写入代码、Issue 或聊天。
6. 打开 [Actions 工作流页面](../.github/workflows/tianlong-to-drive.yml)，点击 **Run workflow**。首次运行成功后，Google Drive 的「金庸MOD」文件夹会出现「天龙八部_三版本」。

注意：ChatGPT 的 Google Drive 授权不等于 GitHub Actions 获得相同凭证。首次 GitHub Actions 自动上传依赖上述 Google 授权；未授权前不应宣称已上传。Google 个人账号可以使用 rclone OAuth，毋须把 Drive 文件夹公开给任何人。若 rclone 使用自建 OAuth 客户端，须确保刷新令牌长期有效（Google OAuth 测试模式的刷新令牌可能 7 天过期）。

## 数据准确性

- CSV 中“邻近人物”仅为机器候选，**不代表此人一定使用或学会相邻武功**。
- 例：玄慈提到“庄帮主降龙掌”，属于他对丐帮帮主应有武功的说法，**不是**庄聚贤实际施展降龙掌的证据。
- 新修版的降龙廿八掌与三联版的降龙十八掌须分版本表示，不可因为名称像就视为完全相同功法。
- 任何分析增量应与既有 Notion 的 W14、版本删改 INDEX、降龙掌传承主档关联，不新建冗余页面。

文本的取得、私人储存和使用需遵守适用的版权及来源许可；本仓库只含下载及研究程序，不再分发受版权保护全文。