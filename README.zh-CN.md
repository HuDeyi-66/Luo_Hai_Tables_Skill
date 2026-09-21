<p align="center">
  <img src="docs/assets/luohai-header.png" alt="LuoHai（海珞）" />
</p>

[English](README.md) | [简体中文](README.zh-CN.md)

# LuoHai（海珞）

**表格证据 Skill**

海珞是一个可以独立运行的开源表格证据 Skill，主要处理 XLSX / 结构化表格证据、上下文、单元格/区域引用与损失可见性。它使用 Python 标准库读取 OOXML 工作簿，识别表格区域，记录工作表与表格上下文，产出单元格与区域证据；原始值与渲染值分开保留；引用可以重建并再次校验。歧义与损失一律如实报出，不做“取第一个匹配”的兜底。

不做静默推断：单元格存在但为空、单元格在表中根本不存在、公式没有缓存值、值读取失败——这四种情况彼此不同，也会以四种不同的方式报出。

## 独立运行是受支持的一等用法

海珞**无需私有 SeaFlow 基座**即可使用：

- 可独立克隆、可独立测试、可独立运行；
- 可集成到其他软件；
- 接入 SeaFlow 时作为官方 Skill / 插件，接入逻辑实现在 SeaFlow 一侧。

---

## 能力范围

下表为 Skill 在运行时声明能力，未列出的能力即未实现。

| 能力 | 支持程度 | 说明 |
| --- | --- | --- |
| 表格证据单元 | supported | 每个识别出的表格区域产出一个证据单元，并携带其工作表与表格上下文 |
| 引用重建 | supported | 单元 payload 携带逐单元格地址、行标签与列标题，足以重建原生引用 |
| 区域定位 | supported | 矩形区域解析为覆盖全部坐标的引用——矩形中的空洞不会被填平 |
| 声明表观察 | partial | 读取 OOXML 表部件（`xl/tables`）并与推断区域比对；声明信息不作为权威 |
| 合并单元格状态 | partial | 读取合并区域；被覆盖的地址报为 merged-from，而不是报成某个值 |
| 富文本片段 | partial | 内联字符串与共享字符串被展平，片段级格式信息丢失 |
| 置信度评分 | unsupported | 记录不确定性与损失状态，但不评分、不排序 |
| CSV 输入 | unsupported | 本切片按架构决定仅支持 XLSX |
| 公式求值 | unsupported | 只读：从 `<f>` 读取公式文本，与缓存值分开保留，缓存值不被求值 |
| 数字格式渲染 | unsupported | 不做样式与数字格式渲染；数值的渲染值与原始值相同 |
| 单元格批注 | unsupported | 不读取批注与线程批注 |
| 内嵌对象 | unsupported | 不读取图表、图片、OLE 对象与数据透视表 |
| 大文件流式读取 | unknown | 无流式路径，整个包一次性读入内存 |

海珞只读取它实现的格式，其余一律拒绝，而不是尝试猜测。

## 安装

确定性路径仅依赖 Python 标准库。无需安装任何包，也无需启动任何服务：

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python --version        # 已在 Windows + CPython 3.13.14 上完成验证
```

以上即为全部安装步骤。

## 最小独立示例

一个函数即构成全部必要接口：

```python
from skills.luohai import run_tabular_evidence

result = run_tabular_evidence("throughput.xlsx", source_id="ports")

print(result.is_complete_success)          # 只要有任何损失，即为 False
for unit in result.units:
    print(unit.address.value, unit.loss)   # 例如 "A1:C3"、('empty', 'absent')
```

`run_tabular_evidence` 接受文件路径、原始字节，或由调用方自行构造的
`TableArtifact`。返回值包含证据单元、运行诊断，以及对“本次读取是否完整”的
如实判断。即使工作簿无法读取，也会返回结果并记录损失或拒绝原因，而不是抛出异常。

也可以直接驱动内部组件：

```python
from skills.luohai import TabularEvidenceSkill, TableArtifact, FixtureXlsxBackend

artifact = TableArtifact.from_file("throughput.xlsx", "ports")
result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id="ports")
```

仓库内另有一个可直接运行的示例：

```bash
python examples/luohai_table_example.py
```

## 测试

```bash
python tests/run_all.py --quiet
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

不需要任何运行时、服务、同级目录或外部路径。仓库内有一组专门的隔离测试来保证这一点：如果 `skills/` 下任何模块引入了私有运行时依赖，测试会失败；同时会检查导入本包不会加载此类模块，并用一个**只包含本仓库**的全新解释器运行入口函数、示例与两个确定性校验脚本。

### 可选对照后端

锁定的 `python-calamine` wheel **不随本仓库分发**，也不是运行时依赖。如果调用方把记录的 wheel 放在 `.spike/python_calamine-0.8.2-cp313-cp313-win_amd64.whl`，会先校验其 SHA-256 与扩展模块的 SHA-256，再加载使用。不提供该 wheel 时，对照测试会跳过——这也是干净检出时的默认结果。

```bash
python tests/run_all.py                  # 可选对照测试跳过
python tests/run_all.py --no-calamine    # 同上，显式声明
```

## 已知限制

* **仅支持 OOXML 工作簿。** 读取 `.xlsx` 与 `.xlsm`；旧版 `.xls` 声明为不支持，而不是尝试解析。不支持 CSV、PDF 与 OCR。
* **不做公式求值。** 只读取公式文本；缓存值不等于求值结果，海珞也不会去计算。
* **不做数字格式渲染。** 数值的渲染值与其原始值相同。
* **声明表信息不作为权威。** 声明元数据只用于与观察结果比对，两者都不被当作权威。
* **未读取的包部件会被报出，而不是被忽略。** 批注、绘图、图表、媒体、数据透视表与 VBA 都会作为未读内容暴露。
* **不做跨 Skill 排序。** 本 Skill 不会把某张表与其他对象做排序比较。
* **平台验证范围。** 已在 Windows + CPython 3.13.14 上完成验证。确定性路径只依赖标准库，因此并未绑定该环境，但其他版本与平台尚未验证。

## 与 SeaFlow 的关系

海珞与海珊是两个独立发布的开源 Skill。SeaFlow 可以将海珞作为官方 Skill / 插件接入；独立运行不要求访问私有 SeaFlow 基座。

依赖方向只有一条：

```
SeaFlow（私有运行时）  ---适配--->  LuoHai（本仓库）
```

海珞从不导入 SeaFlow；即使完全不使用 SeaFlow，本仓库也不会有任何变化。

* SeaFlow 公开信息入口：<https://github.com/HuDeyi-66/SeaFlow>

本节链接均为**发现性链接**，不构成运行时依赖声明。

## 与海珊的关系

海珊（ShanHai）—— 法律文本证据 Skill —— 是海珞的**兄弟 Skill**，而不是依赖项。两个 Skill 互不导入，这一隔离由测试保证。

* 海珊仓库：<https://github.com/HuDeyi-66/Shan_Hai_Code_Skill>

## 许可证

MIT，详见 `LICENSE`。

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

本许可证仅覆盖本仓库。它不延伸到单独维护的私有 SeaFlow 基座；本仓库不对其作出任何许可声明。详见 `DEPENDENCIES.md`。
