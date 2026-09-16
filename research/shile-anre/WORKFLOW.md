# 石勒／羯胡语言 ANRE 工作流 v1.1

## 目标
把《石勒皇帝与羯胡人之谜》中所有语言主张拆成可复跑模型，而不是逐词凭直觉判断。最终问题不是“哪个词最像”，而是“哪一套历史语言模型在年代、地点、形态、语音、来源独立性、patch cost 与 holdout 上整体解释力最高”。

v1.1 的关键升级：**不再让一组人工 seed prior 直接决定顺序**。旧 `hypothesis_matrix.csv` 只保留为 v1.0 对照；主判断改为可追溯的 evidence ledger → gloss-hidden blind fit → ablation → gloss reveal。

## 数据层
1. **Attested Forms**：原文、版本、页码、人物、地点、年代、传世释义。
2. **Variant Graph**：羯/羌、劬/助/句又等异文全部并列，不抢先合并。
3. **Speaker/Event Graph**：谁说、何时说、在何地、属于哪个政权/族群、与哪些语言群有接触。
4. **4C Transcription Lattice**：不假装存在唯一“328 年标准读音”；并列 Shimunek 2015 与 Vovin 2016 所用的两套已发表汉语转写层，先看结论是否跨系统稳定。
5. **Year-Sound Queue**：每个待比较词必须绑定目标年代；没有年代音值的只进入 TODO，不准直接拿现代音比较。
6. **Candidate Languages**：Old Arin/Yeniseian、Early Turkic、接触模型、Null、作者多语拼接控制组分开建模。
7. **Evidence Ledger**：每个加分和扣分都必须有 evidence id、dimension、source 与 claim，禁止只写一个看似精确的总分。

## 双跑
### A. 石旭昊作者玩法复现
现代/书中表面音 → 英文 gloss → 多语词典搜音似义近 → 拼接 → 连读判断。

用途：复原作者究竟是怎样找到候选词，不把他的发现丢掉。

### B. ANRE v1.1
Attested Forms → Entity Split → Source-family collapse → Variant Graph → 4C published-reconstruction lattice → **gloss hidden** → whole-phrase candidate parse → evidence ledger → morphology/chronology/geography/free-parameter/transcription-cost → ablation → gloss reveal → null model → chronological holdout。

## Blind Fit：这次真正防止“看答案做题”
`research/shile-anre/blind_candidates_v1.json` 里，`blind=true` 的证据可以进入第一轮；传统汉文 gloss 相关的 semantic evidence 全部标成 `blind=false`。

第一轮只允许模型看：
- 两套汉语转写层；
- 候选语言自身的形态；
- 年代与地理；
- 需要多少 zero mapping / compression / hypothetical suffix；
- 独立学术批评。

第二轮 `GLOSS_REVEAL` 才加入“軍／出／劉曜胡位／捉”。

## Ablation
至少固定跑四刀：
- `BLIND_ALL`：完整盲跑；
- `NO_MORPHOLOGY`：拔掉形态证据，看当前领先是否全靠 morphology；
- `NO_META_LITERATURE`：拔掉后世学者的总评/批评，只看底层证据；
- `GLOSS_REVEAL`：最后揭示汉文释义。

**关键判据**：如果拔掉一个维度 leader 就换人，那么当前结论只能写“依赖该维度的强假说”，不能 LOCK。

## 当前两套 published 4C channel
十字句统一按位置保存：`秀 支 替 戾 岡｜僕 谷 劬 禿 當`。

- Shimunek et al. 2015：`suw ke they leyr kaN | bok luk gu tukh taN`（作者的 Northern EMC layer）
- Vovin et al. 2016 / Bonmann-Fries 转引：`sjuwH ke tʰejH lejH kaŋ | bok kok guo tʰok taŋ`

当前最重要的事实不是“哪套一定正确”，而是：**10 字中 9 字至少 broad-match，谷是唯一被标记为 MAJOR_DIVERGENCE 的位置：Shimunek = luk，Vovin = kok。** 因此以后任何模型若恰好靠选择自己喜欢的“谷”读法才成立，都要额外扣自由度。

## 当前候选模型
### Old Arin / Yeniseian
Published analysis：`śuke | t-il-ek-aŋ | Bokkok | got-o-kt-aŋ`。

强项：重复 `-aŋ` finite pattern；Bonmann-Fries 进一步提出第二谓词的 `-taŋ` 有 Arin 特异的 3PL 平行；`ke` 与 Arin `kel` 的音义关系在 gloss reveal 后是额外支持。

必须保留的反证：Savelyev & Jeong 2020 对较早 Pumpokol 方案提出“未见证 morpheme / unmatched units”批评；新 Old Arin refinement 不能把这个历史问题直接删掉。

### Early Turkic
Shimunek 2015 published analysis：`su-Ø | kete-r erkan | boklug-gu | tukta-ŋ`。

强项：完整 Turkic parse；`-ŋ` imperative 有 Turkic 内部比较；gloss reveal 后 `sü`、`ket-` 有直观语义对应。

当前成本：`秀支 → su-Ø` 含 zero-mapped written syllable；作者自己指出 `erkan` 不合其所设 Old Turkic vowel harmony；`boklug-gu` 的 case history 需要额外重构；后续研究对其 historical phonology 提出强批评。

### Yeniseian-Turkic contact
Ünal 2026 强化的是**接触史实的可行性**，不是“这句话必然混语”。所以模型允许 contact 做 chronology/geography prior，但 phrase-level switching 没有独立证据时必须付 switch cost。

## 强制规则
- 不用现代普通话直接证明四世纪外来语词源。
- 高僧传与晋书若属于同一佛图澄传统，不能计成两个独立证据。
- 同一候选语言必须用相对稳定的音变/形态规则解释多个词；每词临时换规则记为 patch cost。
- 先盲拟合，再揭示传统 gloss，防止语义锚定。
- Contact ≠ 任意拼语言；没有独立 code-switch boundary 就扣分。
- Legacy weighted score 和 v1.1 evidence-balance 都**不是历史概率**。
- FACT / INFERENCE / STRONG HYPOTHESIS / OPEN HYPOTHESIS / CANON 必须分栏。

## 当前 Information Gain
1. **谷**：独立 Later Han / Northern EMC 证据到底更支持 `luk` 还是 `kok`，还是两者各有方言/层次条件？
2. **Arin morphology audit**：逐个回源 `-taŋ`、`-aŋ` 及 verb-template 内部 slot，确认不是从 couplet 反推出来再拿来证明 couplet。
3. **Turkic transcription-cost audit**：把 zero mapping、one-to-many mapping、hypothetical morphology 全部显式计数。
4. **74-term holdout**：前三项冻结后再跑全书 74 核心词，禁止看 holdout 后调权重。

## GitHub Actions
`.github/workflows/shile-anre-model.yml`

每次模型、query pack、脚本或研究文档变化时自动：
- 跑 unittest；
- 生成 variant graph；
- 生成 legacy hypothesis matrix；
- 生成 4C phonology lattice；
- 生成 gloss-hidden blind fit matrix；
- 生成 evidence ledger；
- 跑 4 组 ablation；
- 生成 year-sound queue 与 next-search；
- 上传 90 天 artifact。

## 输出
- `variant_graph.json`
- `hypothesis_matrix.csv`（legacy）
- `phonology_queue.csv`
- `phonology_lattice_4c.csv`
- `blind_fit_matrix.csv`
- `evidence_ledger.csv`
- `blind_ablation.csv`
- `ablation_summary.json`
- `run_manifest.json`
- `next_search.json`
- `report.md`

## 扩展接口
下一版把本地/Drive 的全书 OCR 抽取结果转换为结构化 JSONL，再用同一 pipeline 批跑。受版权保护的整本 OCR 不进公开仓库；GitHub 保存 workflow、短引文、结构化索引和衍生矩阵，原始大文件继续留在 Drive。
