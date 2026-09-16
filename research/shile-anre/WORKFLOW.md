# 石勒／羯胡语言 ANRE 工作流 v1.0

## 目标
把《石勒皇帝与羯胡人之谜》中所有语言主张拆成可复跑模型，而不是逐词凭直觉判断。最终问题不是“哪个词最像”，而是“哪一套历史语言模型在年代、地点、形态、语音、来源独立性和 holdout 上整体解释力最高”。

## 数据层
1. **Attested Forms**：原文、版本、页码、人物、地点、年代、传世释义。
2. **Variant Graph**：羯/羌、劬/助/句又等异文全部并列，不抢先合并。
3. **Speaker/Event Graph**：谁说、何时说、在何地、属于哪个政权/族群、与哪些语言群有接触。
4. **Year-Sound Queue**：每个待比较词必须绑定目标年代；没有年代音值的只进入 TODO，不准直接拿现代音比较。
5. **Candidate Languages**：Old Arin/Yeniseian、Early Turkic、接触共同语、Hebrew/Aramaic、Iranian 等分开建模。

## 双跑
### A. 石旭昊作者玩法复现
现代/书中表面音 → 英文 gloss → 多语词典搜音似义近 → 拼接 → 连读判断。

用途：复原作者究竟是怎样找到候选词，不把他的发现丢掉。

### B. ANRE
Attested Forms → Entity Split → Source-family collapse → Variant Graph → Sliding Window / Exonym Loss → 4C phonology lattice → latent Z → Blind Fit → morphology → chronology/geography gate → ablation → null model → chronological holdout。

## 强制规则
- 不用现代普通话直接证明四世纪外来语词源。
- 高僧传与晋书若属于同一佛图澄传统，不能计成两个独立证据。
- 同一候选语言必须用相对稳定的音变/形态规则解释多个词；每词临时换规则记为 patch cost。
- 先盲拟合，再揭示传统 gloss，防止语义锚定。
- 所有模型评分只是诊断 prior，不是历史事实评级。
- FACT / INFERENCE / STRONG HYPOTHESIS / OPEN HYPOTHESIS / CANON 必须分栏。

## 当前 P0
1. 校勘“此羯語也 / 此羌語也”是否真为版本异文，还是 OCR/数字文本问题。
2. 对十字句逐字建立约 300–400 CE 的汉语转写音格，不只使用 601 年《切韵》层。
3. 对 `秀支｜替戾岡｜僕谷｜劬禿當` 做 whole-phrase morphology blind fit。
4. 再扩到书中高优先词：羯、羯胡、羌渠、单于、可汗、羯德、莫难、俺、阿弥、舍玛。

## GitHub Actions
`.github/workflows/shile-anre-model.yml`

每次模型、query pack、脚本或研究文档变化时自动：
- 跑 unittest；
- 生成 variant graph；
- 生成 hypothesis matrix；
- 生成 year-sound queue；
- 生成 next-search 信息增益队列；
- 上传 90 天 artifact。

## 输出
- `variant_graph.json`
- `hypothesis_matrix.csv`
- `phonology_queue.csv`
- `run_manifest.json`
- `next_search.json`
- `report.md`

## 扩展接口
下一版把本地/Drive 的全书 OCR 抽取结果转换为结构化 JSONL，再用同一 pipeline 批跑。受版权保护的整本 OCR 不进公开仓库；GitHub 保存 workflow、短引文、结构化索引和衍生矩阵，原始大文件继续留在 Drive。
