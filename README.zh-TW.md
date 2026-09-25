<p align="center">
  <img src="docs/assets/luohai-header.png" alt="LuoHai（海珞）" />
</p>

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

# LuoHai（海珞）

**表格證據 Skill**

海珞是一個可以獨立使用的開源表格證據 Skill，用於結構化表格證據的抽取與引用重建。它使用 Python 標準庫讀取 OOXML 活頁簿，辨識表格區域，記錄工作表與表格脈絡，產出儲存格與區域證據；原始值與顯示值分開保留；引用可以重建並再次校驗。歧義與損失一律如實報出，不做「取第一個匹配」的兜底。

## 獨立使用是受支援的一等用法

海珞**無需私有 SeaFlow 基座**即可使用：

- 可獨立複製（clone）、可獨立測試、可獨立執行；
- 可整合到其他軟體；
- 接入 SeaFlow 時作為官方 Skill / 外掛，接入邏輯實作在 SeaFlow 一側。

---

<p align="center">
  <img src="docs/assets/luohai-comic.png" alt="LuoHai（海珞）能力與邊界示意" />
</p>

## 海珞解決什麼問題

活頁簿是文件，不是資料庫。儲存格裡看到的值，可能是手動輸入的，可能來自共用字串，可能是公式算出來的，也可能根本不存在——因為那個儲存格在表裡就沒有。多數工具會把這幾類情況悄悄壓平：把公式算掉、把數字格式化、把缺口填成空字串；於是結果再也回溯不到檔案裡實際寫了什麼。

海珞反過來做：按檔案原本的寫法讀取，原始值與顯示值分開保留，明確區分儲存格是**存在但為空**還是**在表中不存在**，把錯誤儲存格報成錯誤而不是空白，並把所有沒讀到的內容顯式報出而不是丟棄。它產出的每個單元都帶有足夠精確的座標，可以重建出能被再次校驗的引用。

> **整理證據 ≠ 創造證據**
> **Organising evidence ≠ creating evidence**
>
> 海珞只對**實際觀察到**的表格證據做正規化與結構化整理。它不編造缺失值，不推斷檔案並不支持的事實，也不充當通用分析引擎。

## 能力範圍

下表為 Skill 在執行時宣告的能力，未列出的能力即未實作。

| 能力 | 支援程度 | 說明 |
| --- | --- | --- |
| 表格證據單元 | supported | 每個辨識出的表格區域產出一個證據單元，並攜帶其工作表與表格脈絡 |
| 引用重建 | supported | 單元 payload 攜帶逐儲存格位址、列標籤與欄標題，足以重建原生引用 |
| 區域定位 | supported | 矩形區域解析為覆蓋全部座標的引用——矩形中的空洞不會被填平 |
| 空與不存在 | supported | 存在但為空的儲存格記為 `empty`；表中不存在的儲存格記為 `absent`，這是兩件不同的事實 |
| 錯誤狀態 | supported | 錯誤儲存格報為錯誤，而不是報成空白 |
| 公式文本 | supported | 公式文本從 `<f>` 讀取，並與快取值分開保留 |
| 隱藏工作表狀態 | supported | 工作表狀態從 `workbook.xml` 讀取 |
| 宣告表觀察 | partial | 讀取 OOXML 表部件（`xl/tables`）並與推斷區域比對；宣告資訊不作為權威 |
| 合併儲存格狀態 | partial | 讀取合併區域；被覆蓋的位址報為 merged-from，而不是報成某個值 |
| 富文本片段 | partial | 內嵌字串與共用字串被展平，片段級格式資訊遺失 |
| 置信度評分 | unsupported | 會記錄不確定與損失狀態，但不對證據打分或排序 |
| CSV 輸入 | unsupported | 本切片依架構決定只處理 XLSX |
| 舊版 `.xls`（BIFF） | unsupported | 不解析該二進位格式；會被拒絕，而不是嘗試解析 |
| 公式求值 | unsupported | 唯讀；讀取公式文本，但快取值不會被求值或重算 |
| 數字格式渲染 | unsupported | 不做樣式或數字格式渲染；數字的顯示值等於原始值 |
| 儲存格註解 | unsupported | 不讀取註解與執行緒註解 |
| 內嵌物件 | unsupported | 不讀取圖表、圖片、OLE 物件與樞紐分析表 |
| 大檔案串流讀取 | unknown | 沒有串流路徑；整個封裝會被讀入記憶體 |

海珞只讀取它已實作的格式，其餘一律拒絕，而不是猜測。

## 來源可追溯性如何保留

* **原始值與顯示值分開。** 儲存格的顯示值不會悄悄替換它來源的原始值。
* **空白儲存格不等於缺失儲存格。** `empty` 與 `absent` 是兩種狀態，也按兩種狀態報出。
* **沒讀到的內容會被顯式報出。** 註解、繪圖、圖表、媒體、樞紐分析表與 VBA 都作為未讀取內容報出而不是被忽略，因此「讀得乾淨」不能掩蓋它們。
* **宣告資訊不是權威。** 封裝內宣告的表格中介資料會與實際觀察到的區域比對，任何一方都不覆蓋另一方。
* **歧義是一種結果。** 選擇器匹配到多個位置時傳回全部候選且不選中任何一個，不存在「取第一個」的兜底。
* **證據綁定到位元組。** 證據單元攜帶工件的內容摘要，因此抽出的引用可以對照它來源的那個確切檔案再次校驗。

## 安裝

確定性路徑只依賴標準庫。無需安裝套件，也無需啟動服務：

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python --version        # 已在 Windows + CPython 3.13.14 上通過資格驗證
```

安裝到此為止。

## 最小獨立範例

整個必需介面只有一個函式：

```python
from skills.luohai import run_tabular_evidence

result = run_tabular_evidence("throughput.xlsx", source_id="ports")

print(result.is_complete_success)          # 有任何內容遺失即為 False
for unit in result.units:
    print(unit.address.value, unit.loss)   # 例如 "A1:C3", ('empty', 'absent')
```

`run_tabular_evidence` 接受檔案路徑、原始位元組，或你自己建構的 `TableArtifact`。它傳回的 run 結果帶有證據單元、執行診斷，以及對本次讀取是否完整的如實判斷。即使一個活頁簿無法讀取，也會傳回結果並把損失或拒絕原因記錄在案，而不是拋出例外。

如果需要更底層的入口：

```python
from skills.luohai import TabularEvidenceSkill, TableArtifact, FixtureXlsxBackend

artifact = TableArtifact.from_file("throughput.xlsx", "ports")
result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id="ports")
```

倉庫內還有一個可直接執行的範例：

```bash
python examples/luohai_table_example.py
```

## 測試

```bash
python tests/run_all.py --quiet
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

不需要執行環境、服務、同目錄兄弟倉庫或任何外部路徑。專門的隔離測試套件對此作出證明：只要 `skills/` 下任何模組引入了私有執行環境的 import 就會失敗；它同時檢查 import 本套件不會載入此類模組，並在 `PYTHONPATH` **只包含本倉庫**的全新解譯器中執行入口函式、範例與兩個確定性校驗指令碼。

### 可選的對照後端

鎖定版本的 `python-calamine` wheel **不隨本倉庫散布**，也不是執行期相依。如果你把記錄的 wheel 放到 `.spike/python_calamine-0.8.2-cp313-cp313-win_amd64.whl`，使用前會先複核它的 SHA-256 及其擴充模組的 SHA-256。沒有它時對照測試會跳過——乾淨複製所報告的就是這種情況。

```bash
python tests/run_all.py                  # 可選的對照測試會跳過
python tests/run_all.py --no-calamine    # 同上，但顯式聲明
```

## 已知限制

* **僅支援 OOXML 活頁簿。** 可讀取 `.xlsx` 與 `.xlsm`；舊版 `.xls` 被聲明為不支援，而不是嘗試解析。不支援 CSV、PDF 或 OCR。
* **不做公式求值。** 公式文本會被讀取；快取值不等於求值結果，海珞也不會計算它。
* **不做數字格式渲染。** 數字儲存格的顯示值等於其原始值。
* **宣告表不具權威性。** 宣告的表格中介資料會與觀察結果比對，二者都不被視為權威。
* **未讀取的封裝內部件會被報出，而不是被忽略。** 註解、繪圖、圖表、媒體、樞紐分析表與 VBA 都會作為未讀取內容浮現。
* **不做跨 Skill 排序。** 這裡不會把一張表與另一張表做排序比較。
* **整包讀入記憶體。** 沒有串流路徑，因此未處理超大活頁簿。
* **平台資格。** 已在 Windows + CPython 3.13.14 上通過驗證。確定性路徑只依賴標準庫，因此並未綁死在該環境，但其他版本與平台尚未驗證。

## 與 SeaFlow 的關係

海珞是兩個獨立發布的開源 Skill 之一。SeaFlow 可以把它接入為官方 Skill / 外掛；獨立使用不需要存取私有 SeaFlow 基座。

相依方向是單向的：

```
SeaFlow（私有執行環境）  ---適配--->  LuoHai（本倉庫）
```

海珞從不匯入 SeaFlow。即使你完全不使用 SeaFlow，本倉庫也不受影響。

* SeaFlow 公開資訊入口：<https://github.com/HuDeyi-66/SeaFlow>

本節連結是**發現入口**，不是執行期相依宣告。

## 與海珊（ShanHai）的關係

海珊（ShanHai）—— 法律文本證據 Skill —— 是海珞的**兄弟 Skill**，不是相依。兩個 Skill 互不匯入，且該隔離由測試斷言保證。

* 海珊倉庫：<https://github.com/HuDeyi-66/Shan_Hai_Code_Skill>

## 授權條款

MIT，見 `LICENSE`。

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

本授權條款涵蓋本倉庫，不延伸至單獨維護的私有 SeaFlow 基座執行環境；本倉庫不對其作任何授權聲明。詳見 `DEPENDENCIES.md`。
