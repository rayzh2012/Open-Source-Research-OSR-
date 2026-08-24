# Gonggong–Nüwa Source-Ancestor Candidate Ledger v0.1

Status: **SOURCE-CRITICAL RESEARCH LEDGER**

Run: `m5-exact-source-ancestor-smoke-001`

## Purpose
Identify the textual / exegetical / circulating learned-tradition ancestor(s) behind Wang Chong's `儒书言` fusion of `共工触不周山` with `女娲补天`, without treating modern retellings as evidence of antiquity.

## Run design
- Router: `m5-router-fusion-chronology-001`
- Top routed shards: 12
- Raw bytes read: 17,212,734,025
- Selected evidence rows: 311
- Every selected local window is required to contain at least one source-critical marker such as `论衡 / 淮南子 / 列子 / 三皇本纪 / 儒书言 / 王充 / 高诱 / 天文训 / 览冥训`.
- 131 selected rows expose usable metadata.
- Sampling is deliberately high-yield and bounded; counts are not corpus prevalence estimates.

## Candidate ladder

### C1 — `论衡·谈天` / `顺鼓`
Role: **earliest extant explicit fusion currently verified**.

Evidence:
- `谈天` attributes to `儒书` the chain Gonggong loses to Zhuanxu → strikes Buzhou → heavenly pillar/earth cord fail → Nüwa repairs heaven and establishes the four poles.
- `顺鼓` repeats the joined tradition as `传又言`.

Status: **PRIMARY EXTANT TERMINUS ANTE QUEM**.

What it proves:
- The causal fusion existed by Wang Chong's lifetime.

What it does not prove:
- Wang Chong invented it.
- `儒书` is the title of one identifiable book.

### C2 — Wang Chong's category-level use of `儒书`
Role: **citation-formula evidence**.

The source-critical corpus includes modern historical scholarship observing that Wang's `儒书` can refer broadly across texts/traditions such as `山海经 / 史记 / 尸子 / 淮南子 / 周髀算经`, rather than one narrow Confucian canon or a book titled *Rushu*.

Status: **STRONG SUPPORT FOR CATEGORY-LABEL MODEL**.

Consequence:
The research target is an ancestor **tradition / source bundle / exegetical synthesis**, not necessarily a single lost title.

### C3 — Western-Han `淮南子` motif bundle
Role: **major upstream material reservoir, but not a verified fused ancestor in the extant text**.

Relevant configurations:
- `天文训`: Gonggong vs Zhuanxu → Buzhou damage; no Nüwa in the verified passage.
- `览冥训`: Nüwa repairs heaven / establishes four poles / flood-disaster complex; no Gonggong as cause in the verified passage.
- `原道训`: Gonggong vs Gaoxin → Buzhou; incompatible opponent/chronology with `天文训`.
- `本经训`: Gonggong flood material associated with the Shun/Yu horizon; no Nüwa in the relevant sequence.

Status: **UPSTREAM PARALLEL COMPLEXES**.

Interpretation:
Extant Huainanzi supplies ingredients that a later learned synthesis can combine, but currently does not furnish the exact fused chain attested in Lunheng.

### C4 — Gao You's Huainanzi commentary
Role: **lineage/version discriminator, not a fusion source**.

Evidence:
- `共工，官名` and `其后子孙` at the Gonggong/Zhuanxu tradition.
- another Gonggong explicitly distinguished from the Yao-era Gonggong (`非尧时共工也`).
- Nüwa's four-pole repair remains explained through a separate Three-Sovereigns teaching frame.

Status: **EASTERN-HAN COMMENTARIAL EVIDENCE FOR MULTIPLE GONGGONG LAYERS**.

Interpretation:
This weakens any single-biography harmonization and does not supply a missing pre-Wang causal bridge.

### C5 — Received `列子·汤问`
Role: **counter-model / noncausal ordering**.

The received sequence places Nüwa's repair before `其后` Gonggong strikes Buzhou.

Status: **TEXTUAL COUNTEREXAMPLE**.

Caveat:
Received Liezi's textual history is complicated; its current wording cannot be used as a securely pre-Qin date without a separate transmission audit.

### C6 — Sima Zhen `补史记三皇本纪`
Role: **later narrative smoothing / canonization**.

This text gives the familiar clean chain in a historical-genealogical narrative form and says the matter comes from Huainanzi.

Status: **LATER SYNTHESIS, NOT EVIDENCE THAT EXTANT HUAINANZI ALREADY HAD THE SAME SINGLE PASSAGE**.

### C7 — Lü Simian `读史札记·女娲与共工`
Role: **modern independent textual-critical support for the split/fusion model**.

The source-critical run recovered a metadata-resolved row from `《吕思勉文集：读史札记》[上下]`. Lü compares `览冥 / 原道 / 天文 / 本经 / 楚辞 / 山海经 / 论衡 / 补三皇本纪` and explicitly observes:
- Nüwa material in `览冥` does not mention Gonggong;
- Gonggong flood/damage materials do not necessarily mention Nüwa;
- `论衡` joins the traditions;
- Sima Zhen follows the joined stream.

He characterizes the process as old traditions being mistakenly/secondarily combined.

Status: **STRONG MODERN VERSION-CRITICAL CORROBORATION; NOT AN ANCIENT ANCESTOR**.

### C8 — Modern ritual / mythology / art-history scholarship
Role: **transmission witnesses only**.

The source-critical sample contains many academic and ethnographic works quoting the Lunheng fusion, comparing it with minority traditions, ritual four-pole structures, jade/heaven imagery, etc.

Status: **SECONDARY RECEPTION / COMPARATIVE MATERIAL**.

These rows are useful for mapping later persistence and reinterpretation, not for dating the original fusion.

## Negative result that matters
Within the current **311-row, top-12-shard, source-critical sample**, no named text earlier than Wang Chong has yet been identified that unambiguously states the full causal chain:

`共工触不周山 → 天穹破坏 → 女娲因此补天/立四极`.

This is a meaningful negative result but **not an exhaustive proof of absence**, because:
- only one corpus (`Literature-zh`) contributes to this sample;
- routing is top-shard/high-yield rather than exhaustive source-bibliography sampling;
- lost works and quotation fragments may survive outside the corpus.

## Current best model
`separate / variable earlier myth complexes`
→ `learned textual circulation and convergence`
→ **fusion attested explicitly by Wang Chong**
→ `continued competing arrangements`
→ `later clean historical/mythographic canonization (e.g. Sima Zhen)`
→ `modern mass-retelling fusion`.

## Promotion gates
- Do not promote `Wang Chong invented the fusion`.
- Do not promote `儒书 = a single lost book`.
- Do not promote `Huainanzi already contained the exact Sima Zhen sequence`.
- Do not use modern fiction/folklore restatements to date an ancient textual motif.
- Any proposed pre-Wang ancestor must have exact work/fragment identity, date/transmission argument, and wording sufficient to demonstrate the causal link.

## Next highest-information searches
1. Han–Jin quotation/commentary chains around Wang Chong, Gao You, Wang Yi, Ying Shao, Zhang Zhan.
2. `太平御览 / 艺文类聚 / 初学记` quotations that may preserve lost earlier wording.
3. Lost-book fragments and leishu quotations using `共工 / 不周 / 女娲 / 五色石 / 四极` in one causal passage.
4. Dedicated transmission audit of received `列子·汤问`.
5. Broader source-critical routing only if these compact citation chains fail to identify an earlier witness.
