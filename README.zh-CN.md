<p align="center">
  <img src="docs/assets/luohai-header.png" alt="LuoHai（海珞）" />
</p>

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

# LuoHai（海珞）

**表格证据 Skill**

海珞是一个可以独立使用的开源表格证据 Skill，用于结构化表格证据的抽取与引用重建。它使用 Python 标准库读取 OOXML 工作簿，识别表格区域，记录工作表与表格上下文，产出单元格与区域证据；原始值与渲染值分开保留；引用可以重建并再次校验。歧义与损失一律如实报出，不做“取第一个匹配”的兜底。

## 独立使用是受支持的一等用法

海珞**无需私有 SeaFlow 基座**即可使用：

- 可独立克隆、可独立测试、可独立运行；
- 可集成到其他软件；
- 接入 SeaFlow 时作为官方 Skill / 插件，接入逻辑实现在 SeaFlow 一侧。

---

<p align="center">
  <img src="docs/assets/luohai-comic.png" alt="LuoHai（海珞）能力与边界示意" />
</p>

## 海珞解决什么问题

工作簿是文档，不是数据库。单元格里看到的值，可能是手工输入的，可能来自共享字符串，可能是公式算出来的，也可能根本不存在——因为那个单元格在表里就没有。多数工具会把这几类情况悄悄压平：把公式算掉、把数字格式化、把缺口填成空字符串；于是结果再也回溯不到文件里实际写了什么。

海珞反过来做：按文件原本的写法读取，原始值与渲染值分开保留，明确区分单元格是**存在但为空**还是**在表中不存在**，把错误单元格报成错误而不是空白，并把所有没读到的内容显式报出而不是丢弃。它产出的每个单元都带有足够精确的坐标，可以重建出能被再次校验的引用。

> **整理证据 ≠ 创造证据**
> **Organising evidence ≠ creating evidence**
>
> 海珞只对**实际观察到**的表格证据做规范化与结构化整理。它不编造缺失值，不推断文件并不支持的事实，也不充当通用分析引擎。

## 能力范围

下表为 Skill 在运行时声明能力，未列出的能力即未实现。

| 能力 | 支持程度 | 说明 |
| --- | --- | --- |
| 表格证据单元 | supported | 每个识别出的表格区域产出一个证据单元，并携带其工作表与表格上下文 |
| 引用重建 | supported | 单元 payload 携带逐单元格地址、行标签与列标题，足以重建原生引用 |
| 区域定位 | supported | 矩形区域解析为覆盖全部坐标的引用——矩形中的空洞不会被填平 |
| 空与不存在 | supported | 存在但为空的单元格记为 `empty`；表中不存在的单元格记为 `absent`，这是两件不同的事实 |
| 错误状态 | supported | 错误单元格报为错误，而不是报成空白 |
| 公式文本 | supported | 公式文本从 `<f>` 读取，并与缓存值分开保留 |
| 隐藏工作表状态 | supported | 工作表状态从 `workbook.xml` 读取 |
| 声明表观察 | partial | 读取 OOXML 表部件（`xl/tables`）并与推断区域比对；声明信息不作为权威 |
| 合并单元格状态 | partial | 读取合并区域；被覆盖的地址报为 merged-from，而不是报成某个值 |
| 富文本片段 | partial | 内联字符串与共享字符串被展平，片段级格式信息丢失 |
| 置信度评分 | unsupported | 会记录不确定与损失状态，但不对证据打分或排序 |
| CSV 输入 | unsupported | 本切片按架构决定只处理 XLSX |
| 旧版 `.xls`（BIFF） | unsupported | 不解析该二进制格式；会被拒绝，而不是尝试解析 |
| 公式求值 | unsupported | 只读；读取公式文本，但缓存值不会被求值或重算 |
| 数字格式渲染 | unsupported | 不做样式或数字格式渲染；数字的渲染值等于原始值 |
| 单元格批注 | unsupported | 不读取批注与线程批注 |
| 内嵌对象 | unsupported | 不读取图表、图片、OLE 对象与数据透视表 |
| 大文件流式读取 | unknown | 没有流式路径；整个包会被读入内存 |

海珞只读取它已实现的格式，其余一律拒绝，而不是猜测。

## 来源可追溯性如何保留

* **原始值与渲染值分开。** 单元格的渲染值不会悄悄替换它来源的原始值。
* **空白单元格不等于缺失单元格。** `empty` 与 `absent` 是两种状态，也按两种状态报出。
* **没读到的内容会被显式报出。** 批注、绘图、图表、媒体、数据透视表与 VBA 都作为未读取内容报出而不是被忽略，因此“读得干净”不能掩盖它们。
* **声明信息不是权威。** 包内声明的表格元数据会与实际观察到的区域比对，任何一方都不覆盖另一方。
* **歧义是一种结果。** 选择器匹配到多个位置时返回全部候选且不选中任何一个，不存在“取第一个”的兜底。
* **证据绑定到字节。** 证据单元携带工件的内容摘要，因此抽出的引用可以对照它来源的那个确切文件再次校验。

## 安装

确定性路径只依赖标准库。无需安装包，也无需启动服务：

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python --version        # 已在 Windows + CPython 3.13.14 上通过资格验证
```

安装到此为止。

## 最小独立示例

整个必需接口只有一个函数：

```python
from skills.luohai import run_tabular_evidence

result = run_tabular_evidence("throughput.xlsx", source_id="ports")

print(result.is_complete_success)          # 有任何内容丢失即为 False
for unit in result.units:
    print(unit.address.value, unit.loss)   # 例如 "A1:C3", ('empty', 'absent')
```

`run_tabular_evidence` 接受文件路径、原始字节，或你自己构造的 `TableArtifact`。它返回的 run 结果带有证据单元、运行诊断，以及对本次读取是否完整的如实判断。即使一个工作簿无法读取，也会返回结果并把损失或拒绝原因记录在案，而不是抛出异常。

如果需要更底层的入口：

```python
from skills.luohai import TabularEvidenceSkill, TableArtifact, FixtureXlsxBackend

artifact = TableArtifact.from_file("throughput.xlsx", "ports")
result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id="ports")
```

仓库内还有一个可直接运行的示例：

```bash
python examples/luohai_table_example.py
```

## 测试

```bash
python tests/run_all.py --quiet
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

不需要运行时、服务、同目录兄弟仓库或任何外部路径。专门的隔离测试套件对此作出证明：只要 `skills/` 下任何模块引入了私有运行时的 import 就会失败；它同时检查 import 本包不会加载此类模块，并在 `PYTHONPATH` **只包含本仓库**的全新解释器中运行入口函数、示例与两个确定性校验脚本。

### 可选的对照后端

锁定版本的 `python-calamine` wheel **不随本仓库分发**，也不是运行时依赖。如果你把记录的 wheel 放到 `.spike/python_calamine-0.8.2-cp313-cp313-win_amd64.whl`，使用前会先复核它的 SHA-256 及其扩展模块的 SHA-256。没有它时对照测试会跳过——干净克隆所报告的就是这种情况。

```bash
python tests/run_all.py                  # 可选的对照测试会跳过
python tests/run_all.py --no-calamine    # 同上，但显式声明
```

## 已知限制

* **仅支持 OOXML 工作簿。** 可读取 `.xlsx` 与 `.xlsm`；旧版 `.xls` 被声明为不支持，而不是尝试解析。不支持 CSV、PDF 或 OCR。
* **不做公式求值。** 公式文本会被读取；缓存值不等于求值结果，海珞也不会计算它。
* **不做数字格式渲染。** 数字单元格的渲染值等于其原始值。
* **声明表不具权威性。** 声明的表格元数据会与观察结果比对，二者都不被视为权威。
* **未读取的包内部件会被报出，而不是被忽略。** 批注、绘图、图表、媒体、数据透视表与 VBA 都会作为未读取内容浮现。
* **不做跨 Skill 排序。** 这里不会把一张表与另一张表做排序比较。
* **整包读入内存。** 没有流式路径，因此未处理超大工作簿。
* **平台资格。** 已在 Windows + CPython 3.13.14 上通过验证。确定性路径只依赖标准库，因此并未绑死在该环境，但其他版本与平台尚未验证。

## 与 SeaFlow 的关系

海珞是两个独立发布的开源 Skill 之一。SeaFlow 可以把它接入为官方 Skill / 插件；独立使用不需要访问私有 SeaFlow 基座。

依赖方向是单向的：

```
SeaFlow（私有运行时）  ---适配--->  LuoHai（本仓库）
```

海珞从不导入 SeaFlow。即使你完全不使用 SeaFlow，本仓库也不受影响。

* SeaFlow 公开信息入口：<https://github.com/HuDeyi-66/SeaFlow>

本节链接是**发现入口**，不是运行时依赖声明。

## 与海珊（ShanHai）的关系

海珊（ShanHai）—— 法律文本证据 Skill —— 是海珞的**兄弟 Skill**，不是依赖。两个 Skill 互不导入，且该隔离由测试断言保证。

* 海珊仓库：<https://github.com/HuDeyi-66/Shan_Hai_Code_Skill>

## 许可证

MIT，见 `LICENSE`。

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

本许可证覆盖本仓库，不延伸至单独维护的私有 SeaFlow 基座运行时；本仓库不对其作任何许可声明。详见 `DEPENDENCIES.md`。
