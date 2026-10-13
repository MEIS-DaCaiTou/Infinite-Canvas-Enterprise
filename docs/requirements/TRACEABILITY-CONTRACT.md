# 需求追踪规则与来源登记

日期：2026-10-09。性质：REQUIREMENTS_TRACEABILITY_REFERENCE / NOT_A_TEST_RESULT。文档及 CSV 描述本次核查快照，不承担当前 PR/合并状态播报。

本参考文档服务于唯一需求入口 [PROJECT_SCOPE_LOCK](../../PROJECT_SCOPE_LOCK.md)，不成为第二份路线图/任务队列。决定登记见 [REQUIREMENTS-DECISION-REGISTER](../decisions/REQUIREMENTS-DECISION-REGISTER.md)。

## 1. 独立状态轴

| 轴 | 枚举/含义 |
| --- | --- |
| 需求确认 | CONFIRMED：所述原则已确认；PARTIALLY_CONFIRMED：方向/原则确认但所列细则未批；PENDING_CONFIRMATION：具体政策/设计待确认；PROJECT_BASELINE：现行工程基线约束 |
| 实现 | IMPLEMENTED：仅 verified_reuse 指明的基础已经实现；PARTIAL：已有基础而 remaining_gap 尚缺；NOT_IMPLEMENTED：所述新能力未实现；NOT_VERIFIED：没有该独立产品完成证据，不能猜为已完成/全部未做 |
| 实施授权 | 范围确认和文档合入均不产生新增业务实施许可；NO_NEW_BUSINESS_IMPLEMENTATION_AUTHORIZATION 不否定已有工程诊断授权。历史文档审查授权见决定登记，PR 当前状态另查 GitHub |
| 场景范围 | KEEP_CORE / REWORD_SUPPLEMENT / POLICY_PENDING / LATER_STAGE：82/10/9/3，不是成功/失败或实施排期 |
| 场景执行 | 本次核查快照全部 NOT_RUN；代码能力、历史定向测试、CI、正式 Release、客户反馈必须另外给准确来源，不能替换执行列 |

INDEPENDENT_PRODUCT_OUT 是产品范围，不是删除已有能力。历史行的 PARTIAL 可以描述 retained_contracts/verified_reuse 中的已有基础，绝不表示被移出的独立产品进入施工或已交付。原 P0/P1 是输入包候选风险标记（84/20），不是新正式任务优先级。

## 2. 三张表的列契约

- [REQUIREMENT-TRACEABILITY.csv](./REQUIREMENT-TRACEABILITY.csv)：14 行，原 BR ID/题意/旧决策状态和原场景关系留存；confirmation_status 与 implementation_status 分开；test_ids 是本轮完整回链，draft_refs 仅链接未批准 N37 草案。
- [ACCEPTANCE-SCENARIOS.csv](./ACCEPTANCE-SCENARIOS.csv)：104 行，原 id/domain/scenario/expected/evidence/priority 六列逐字保留。原 evidence 是“预期取证方式”，不是执行结果。current_scenario/current_expected 承载修订，scope_reason 记录范围原因，policy_refs 不把未决变已批。
- [HISTORICAL-PLAN-MAPPING.csv](./HISTORICAL-PLAN-MAPPING.csv)：37 行，原编号、准确题名、原文行号与标题中的历史标签保留。original_heading_label 不是今天的实现状态；当前 scope/implementation/授权单列。源码证据固定到核查 main，不把 PR/Release/现场混用。

列表使用分号分隔、UTF-8、RFC 4180 双引号字段；行按原 ID 顺序。BN 字段中的括号仅说明承接/最小契约范围，不改编号。N30/N31/N33 关联表示保留基础，不让移出独立产品复活。历史表的 N37 场景仅是共用契约基础，不能充当 Connector 专项覆盖。

原 48 条唯一场景挂接全部保留；56 条未挂接场景现在 GAP_FILLED。每个场景有 primary_br 及至少一个 br_ids；BR.test_ids 由同一关系逆向生成，禁止出现正向有而反向没有的关系。一个场景可覆盖多个 BR，但不能只为统计给所有场景挂万能 BR-SYS-01。

## 3. 104 个场景范围冻结

| 类别 | 数量 | ID/边界 |
| --- | ---: | --- |
| KEEP_CORE | 82 | 除下面三组之外的原 T001—T104 |
| REWORD_SUPPLEMENT | 10 | T013、T025、T026、T027、T032、T033、T034、T036、T043、T064 |
| POLICY_PENDING | 9 | T049、T050、T051、T057、T062、T063、T065、T070、T080 |
| LATER_STAGE | 3 | T084 多 Worker、T095 对象存储、T104 员工端缓存 |

删除 0、原 ID 改号 0。十条改写分别去除未批分类前提、明确验收与发布、固定 Bundle 引用而不强制物理去重、补在线撤销与离线 PS 副本边界。九条政策待定仍保留默认拒绝/许可/审计/真实费用等安全边界。三条后续工程不取消单机幂等、稳定 ID 或在线撤销基础。

原 104 条没有完整的跨工具/PS 写回专项验收。N37 新候选仅采用草案语义标签；不得自动生成 T105 等正式 ID，也不得宣称 104 条已覆盖 N37 全部链路。

## 4. 来源登记：原始证据不回写

| 来源键 | 准确身份 | 使用边界 |
| --- | --- | --- |
| SRC-PACK | Infinite-Canvas-Enterprise-Full-Requirements-Handoff-2026-10-09.zip；SHA-256 ac25c0b5597c96e214a3e4f8fbe42c9635679e6d4a56743ebc2499ac9db9fbc2 | 原 21 个成员/14 BR/104 场景/37 行模板，原包不改；输入包指令不单独构成执行授权 |
| SRC-PLAN | 无限画布企业版_新版完整开发规划_2026-10-07.md；SHA-256 5935b00dbcf4cbcd53bcee2de0a7301109641e6727a263c1f82f7dc7406b26d6 | 原文历史设计，不整份视为获批；L133—L407 标题位置从原文逐项核对 |
| SRC-SCOPE-REPORT | 37项历史规划范围修订与需求基线调整报告.zh-CN.md；SHA-256 d6561ff924caa369258a4c1eec82010d8d24874019da771412311d5e79dff048 | 负责人已认可范围分析，不是业务实现或生产验收 |
| SRC-SCOPE-APPENDIX | 验收场景范围影响附表.zh-CN.md；SHA-256 7e0319884e4bdbe216f3bed2e4f883cc2362aa5f53a6e67b28ac83fc47ce20a7 | 82/10/9/3 分组与原场景对应，不是 104 次执行记录 |
| SCOPE-2026-10-09 | 本项目负责人 2026-10-09 范围确认及本轮 Docs-only 授权 | 高于原包未决“是否保留核心模块”；不批准其他未决政策或合并/开发 |
| SRC-MAIN | main@a5a6aa10b7882c46f129ec6df854239ee111da18 | 当前源码核查快照；之后变化需更新证据，不把 Draft Head 当 main |
| SRC-ENGINEERING | [#148](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/148)，2026-10-09 核查 Head 10990775d37ee28e8d4dfd3f9893135538ed3c2f | 当时为 Draft，真实固定 EXE 演练失败；这是历史观察，不是后续 Head/合并状态；绿灯 CI 不是完整闭环通过 |
| SRC-RELEASE | [v2026.10.1](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/releases/tag/v2026.10.1)，bf1143a7bc54ac24d53b9e7d7db5a9b50da8b57c | 已发布资产不改，不等当前 main 或通用生产批准 |

原始文件保留在负责人提供的 Downloads 与仓库外 requirements-intake 证据目录；仓库只保存身份和受控修订，不把原 ZIP/生产数据复制进 Git。首轮 REPORT.zh-CN.md、MAPPING-AND-COVERAGE.zh-CN.md 也保持原状；旧报告中的待审范围由新决定覆盖，不原地美化。

包内 C0—C10 审查分组不变成正式排期。原 N34→N33 见历史原文 L381；N33→N31/N34 在 L369；N31→N33 在 L343；没有 N34→N31 的直接依赖。当前无环关系只见范围入口及 N37 草案。

## 5. 本次文档核验与未验证边界

验收本次文档变更时应分别核对：

1. 37 原编号/准确题名/历史行号，无重复；14 原 BR ID 无改号。
2. T001—T104 唯一、原六列与原 CSV 完全一致；82/10/9/3、84/20 风险来源一致。
3. 104 个 primary_br/br_ids 均有效，BR 反向挂接一致；保留全部旧关系并填 56 条缺口，未映射 0。
4. 确认/实现/实施授权/执行四种信息不混淆；未决政策不自动确认。
5. N37 下位需求标为草案，已有基础与工具专项候选分开；没有新增正式 T ID。
6. 文档登记、链接及冻结原始证据未改；diff 仅文档，正式路线图、源码、数据库与发行资产不动。

CSV 使用表格工具解析、写入与往返核验；运行时原文件哈希另行核对。仓库 tools/check_docs.py 和文档契约单测覆盖 Markdown/text 登记、断链/重复权威和冻结文档，**不验证 CSV 语义**；三张 CSV 作为登记表的 tabular_resources 由本次额外定向核验，不虚称已有 CI 已校验全表。

本次没有执行 T001—T104、真实 Photoshop、付费 Provider、客户登录/生产复查、升级/恢复演练。历史测试仅证明原先有限实现，不能替新部门/版本/工具接口测试。

## 6. 可重复执行的核验与 CI 边界

三张 CSV 的实现/缺口文字均以 SRC-MAIN 的日期/提交为快照，包括 B01 当时的 Draft 描述；不能将旧快照当成未来 `main` 的实时进度。更新该快照须有新源码/工程证据，不由文档合并自动改为已实现。

| 检查入口 | 自动覆盖 | 没有自动覆盖 |
| --- | --- | --- |
| `.github/workflows/documentation-checks.yml` | `tools/check_docs.py`：Markdown/text 登记、唯一权威、冻结文档及本地链接；17 项文档契约单测；提交空白错误 | CSV 逐行语义、原 ZIP/历史规划对比；该 workflow 的 paths 也不含单独 CSV 变更 |
| `.github/workflows/enterprise-checks.yml` 的 Windows 3.11 / Runtime 3.14 | 现有 enterprise/Runtime 单测及各自限定的烟测，详见 workflow 命令 | 不执行下列 CSV 定向块，不将绿灯等同 104 条业务场景、N37 工具专项或 #148 完整固定 EXE 闭环 |
| 下列只读定向块 | 三表身份、数量、状态、分类、双向引用、原关系保留、登记与 N37 临时引用；提供原件后再比对源内容 | 业务语义正确性、政策批准、源码实现及业务场景执行，仍需独立审查/真实测试 |

在仓库根目录以 PowerShell 和 Python 3.11+ 执行。仅标准库、只读、无依赖安装，不改测试系统/CI。任何断言失败返回非零；不得以删除断言、减少行数或改原始证据取得通过。

```powershell
$taskTraceCheck = @'
import collections, csv, hashlib, io, json, re, sys, zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
folder = root / "docs/requirements"
def check(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)
def parse(text):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    check(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "CSV headers")
    rows = list(reader)
    check(all(None not in r and all(v is not None for v in r.values()) for r in rows), "CSV row width")
    return rows
def refs(value):
    values = value.split(";") if value else []
    check(len(values) == len(set(values)), "duplicate reference")
    return set(values)
def index(rows, expected):
    ids = [r["id"] for r in rows]
    check(len(ids) == len(set(ids)) and set(ids) == set(expected), "IDs/counts")
    return {r["id"]: r for r in rows}

br = parse((folder / "REQUIREMENT-TRACEABILITY.csv").read_text(encoding="utf-8"))
bn = parse((folder / "HISTORICAL-PLAN-MAPPING.csv").read_text(encoding="utf-8"))
tests = parse((folder / "ACCEPTANCE-SCENARIOS.csv").read_text(encoding="utf-8"))
br_ids = "BR-OWN-01 BR-PRO-01 BR-PUB-01 BR-AST-01 BR-AST-02 BR-WRK-01 BR-AI-01 BR-COST-01 BR-DATA-01 BR-UPD-01 BR-CLASS-01 BR-DER-01 BR-DEL-01 BR-SYS-01".split()
br_by = index(br, br_ids)
bn_by = index(bn, [f"B{i:02}" for i in range(1, 28)] + [f"N{i:02}" for i in range(28, 38)])
t_by = index(tests, [f"T{i:03}" for i in range(1, 105)])
classes = {"REWORD_SUPPLEMENT": "T013 T025 T026 T027 T032 T033 T034 T036 T043 T064",
           "POLICY_PENDING": "T049 T050 T051 T057 T062 T063 T065 T070 T080",
           "LATER_STAGE": "T084 T095 T104"}
classified = {t: c for c, ids in classes.items() for t in ids.split()}
for t, row in t_by.items():
    linked = refs(row["br_ids"])
    check(row["primary_br"] in linked and linked <= br_by.keys(), "scenario BR: " + t)
    check(row["scope_class"] == classified.get(t, "KEEP_CORE"), "scope class: " + t)
    check(row["execution_status"] == "NOT_RUN", "snapshot execution: " + t)
    check(all(t in refs(br_by[b]["test_ids"]) for b in linked), "reverse BR edge: " + t)
for b, row in br_by.items():
    check(refs(row["test_ids"]) <= t_by.keys(), "unknown T: " + b)
    check(all(b in refs(t_by[t]["br_ids"]) for t in refs(row["test_ids"])), "forward T edge: " + b)
    check(refs(row["original_test_ids"]) <= refs(row["test_ids"]), "old BR edge: " + b)
    check(row["confirmation_status"] in {"CONFIRMED", "PARTIALLY_CONFIRMED", "PENDING_CONFIRMATION", "PROJECT_BASELINE"}, "confirmation: " + b)
    check(row["implementation_authorization"] == "NO_NEW_BUSINESS_IMPLEMENTATION_AUTHORIZATION", "authorization: " + b)
implementation = {"IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED", "NOT_VERIFIED"}
for row in br + bn:
    check(row["implementation_status"] in implementation, "implementation enum")
for row in bn:
    check(refs(row["br_ids"]) <= br_by.keys() and refs(row["candidate_test_ids"]) <= t_by.keys(), "BN edge")
for row in br + tests:
    check(all(re.match(r"[BN]\d{2}", value) and value[:3] in bn_by for value in refs(row["bn_ids"])), "BN ID")
check(collections.Counter(r["original_top_level_mapping"] for r in tests) == {"PRESERVED": 48, "GAP_FILLED": 56}, "48/56 mapping")
check(collections.Counter(r["priority"] for r in tests) == {"P0": 84, "P1": 20}, "original priority")
draft = (folder / "N37-ASSET-INTEROP-CONTRACT-DRAFT.md").read_text(encoding="utf-8")
labels = set(re.findall(r"DRAFT-N37-[A-Z]+(?:-[A-Z]+)*", draft))
check(len(labels) == 11 and set().union(*(refs(r["draft_refs"]) for r in br)) == labels, "N37 draft reverse refs")
check(all(int(t[1:]) <= 104 for t in re.findall(r"T\d{3}", draft)), "new formal scene ID")
register = json.loads((root / "docs/document-register.json").read_text(encoding="utf-8"))
check([r["path"] for r in register["documents"] if r.get("authority") == "scope"] == ["PROJECT_SCOPE_LOCK.md"], "scope authority")
tables = register["tabular_resources"]
check({r["path"] for r in tables} == {"docs/requirements/" + f for f in ("REQUIREMENT-TRACEABILITY.csv", "HISTORICAL-PLAN-MAPPING.csv", "ACCEPTANCE-SCENARIOS.csv")}, "registered tables")
for row in tables:
    check(row["owner"] == "PROJECT_SCOPE_LOCK.md" and len(parse((root / row["path"]).read_text(encoding="utf-8"))) == row["expected_rows"], "table owner/count")

source_zip = "NOT_CHECKED"
source_plan = "NOT_CHECKED"
if len(sys.argv) > 2:
    package = Path(sys.argv[2]).read_bytes()
    check(hashlib.sha256(package).hexdigest() == "ac25c0b5597c96e214a3e4f8fbe42c9635679e6d4a56743ebc2499ac9db9fbc2", "original ZIP hash")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        def member(suffix):
            names = [n for n in archive.namelist() if n == suffix or n.endswith("/" + suffix)]
            check(len(names) == 1, "source member: " + suffix)
            return parse(archive.read(names[0]).decode("utf-8-sig"))
        old_tests = member("03-DELIVERY/ACCEPTANCE-TEST-MATRIX.csv")
        old_br = member("04-GOVERNANCE/TRACEABILITY-MATRIX.csv")
    fields = ("id", "domain", "scenario", "expected", "evidence", "priority")
    check([[r[f] for f in fields] for r in tests] == [[r[f] for f in fields] for r in old_tests], "original six columns/order")
    check([r["id"] for r in br] == [r["pack_requirement_id"] for r in old_br], "original BR order")
    old_mapped = set()
    for row in old_br:
        current = br_by[row["pack_requirement_id"]]
        check(current["original_requirement"] == row["requirement"] and current["original_decision_status"] == row["decision_status"], "original BR meaning/status")
        old = set(filter(None, row["acceptance_test_ids"].split(",")))
        check(old == refs(current["original_test_ids"]) and old <= refs(current["test_ids"]), "original BR edges")
        old_mapped.update(old)
    check(all(r["original_top_level_mapping"] == ("PRESERVED" if r["id"] in old_mapped else "GAP_FILLED") for r in tests), "original 48/56 identity")
    source_zip = "PASS"
if len(sys.argv) > 3:
    original = Path(sys.argv[3]).read_bytes()
    check(hashlib.sha256(original).hexdigest() == "5935b00dbcf4cbcd53bcee2de0a7301109641e6727a263c1f82f7dc7406b26d6", "original plan hash")
    plan = original.decode("utf-8-sig")
    titles = [(i, t.split("【", 1)[0].strip()) for i, t in re.findall(r"^### ([BN]\d{2}) (.+)$", plan, re.M)]
    check([(r["id"], r["exact_original_title"]) for r in bn] == titles, "37 original titles/order")
    lines = plan.splitlines()
    for row in bn:
        line = lines[int(row["original_source_ref"].removeprefix("SRC-PLAN:L")) - 1]
        check(line.startswith("### " + row["id"] + " " + row["exact_original_title"]), "original heading line")
    source_plan = "PASS"
print(json.dumps({"repository_semantics": "PASS", "BR": len(br), "BN": len(bn), "scenes": len(tests),
    "classes": dict(collections.Counter(r["scope_class"] for r in tests)), "execution": "104 NOT_RUN",
    "original_zip_comparison": source_zip, "historical_plan_comparison": source_plan}, ensure_ascii=False))
'@
# 仅仓库内语义；不声称已对比外部原件。
$taskTraceCheck | py -3.11 -B - .
if ($LASTEXITCODE -ne 0) { throw 'Traceability check failed' }
# 完整来源对比：将两条路径替换为保留的原始证据；读取但不解压/改写。
# $taskTraceCheck | py -3.11 -B - . 'C:\path\Infinite-Canvas-Enterprise-Full-Requirements-Handoff-2026-10-09.zip' 'C:\path\无限画布企业版_新版完整开发规划_2026-10-07.md'
```

仓库内结果应为 14/37/104、82/10/9/3、104 NOT_RUN；完整模式额外要求两个来源比较均 PASS。未提供原件时，NOT_CHECKED 必须保留，不能算来源比较通过。普通用户无需下载依赖或运行平台服务。核验结果需要附精确 Head SHA、运行命令及退出码；该块仅检查追踪契约，不判断政策是否获批。
