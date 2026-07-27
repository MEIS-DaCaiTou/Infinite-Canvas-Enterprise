# ENV-1B1C-B2：Portable Runtime Lifecycle 实施记录

- 基线：`main@6610218aecc0b864df5f075cb6824e041daedfd7`。
- 状态：B2 repository implementation 已形成；独立验收和真实 bundled Runtime lifecycle 验证尚未完成。
- 边界：不修改 `main.py` / gateway，不实现 Runtime 重建、Manifest v2、Release activation、OPS-3B、formal Release 或生产操作。

## 固定入口与信任链

正式 Windows wrappers 只调用当前 `APP_ROOT/python/python.exe -I -B` 与固定脚本
`enterprise/runtime/launcher.py portable <command>`；不使用 PATH、cwd 或 `-m` fallback，也不接受
install root、LOCALAPPDATA、Python、manifest 或 context 的 operator override。launcher 在 enterprise import
前校验自身 Release 布局、固定 Python、bytecode policy、manifest 与 pointer 的最小边界。

完整 preflight 按以下顺序建立信任：launcher 自身 → Windows Known Folder LOCALAPPDATA → bounded one-read
`current-release.json` 与 raw SHA-256 → self/pointer/PathRoots → Runtime Manifest startup view → 当前
`sys.executable`/Python identity → DATA/LOG/RUNTIME/CACHE/TEMP writable probes → typed preflight。

## 单一生命周期与 identity

B2 复用 STAB-1 的 `RuntimeController`、`RuntimeSupervisor`、`RuntimeStateStore`、单一 lock 和同一
`instance_id`。启动顺序为 preflight pass → 生成 instance identity → inspect/stale gate → reserve existing
lock → 在锁下发布 launch context → fixed Python 启动 host → supervisor adopt lock → state → fixed child →
readiness。没有第二套 controller、state、lock 或 supervisor。

launch context、lock、runtime state、control document、ACK、host 和 child 绑定相同 release ID、manifest、
preflight、Python、context 与 instance identity。host/child 在导入 config、gateway 或 `main` 前验证该绑定；
child role restart 继续使用同一固定 context 和 Release Python。successful stop 可保留 context 作为受限诊断，
但 context 不单独证明 live ownership。

## Ownership 与 readiness

formal wrapper 不是 current Release 时 fail closed。current start/restart 遇到旧 owned instance 时拒绝隐式
切换；status 保持 exit 0 并报告 mismatch；health 返回 exit 2；current stop 仅在旧 instance ownership 可验证
时允许。status 是诊断接口；health 只有在 state、lock、instance、context、manifest/Python 与两个 listener
六类证据全部通过时才成功。

## 验证与未完成边界

聚焦测试使用 fake/minimal Runtime、临时 roots 和既有 STAB-1 fixture；不访问生产或临时业务设备。
`real_bundled_python_fixture_tests=false`、`fixed_release_python_real_start_chain_verified=false`、
`github_ci_verified=false`、`ENV_1B1C_completed=false`。dependency/archive provenance 仍为 false；formal
Release、Manifest v2、activation、OPS-3B、Production Baseline 和 `production_approved` 均未形成。

## D1–D10 落地映射

| 决定 | 仓库实现 |
| --- | --- |
| D1 | fixed direct `launcher.py`、严格五命令 grammar、`-I -B`、无 PATH/`-m` fallback |
| D2 | self-location、Known Folder、one-read pointer、PathRoots、manifest、Python、probe、preflight 顺序 |
| D3 | `runtime_mode` 与 `host_style` 分离；portable identity 来自 retained context |
| D4 | preflight → instance → inspect → reserve existing lock → context → host/child |
| D5 | 复用现有 controller/supervisor/state/process/health，不建立平行 lifecycle |
| D6 | release/manifest/preflight/context/instance/process/listener 的完整 ownership 组合 |
| D7 | context 在 existing reservation 下发布，host adopt 同一 lock |
| D8 | 六项 readiness；status 诊断 exit 0，health 只有完整 ready 才 exit 0 |
| D9 | start/stop/restart/status/health 五个 UTF-8 Windows wrappers |
| D10 | development STAB-1 保持兼容；server、activation、Manifest v2 继续 fail closed/未实施 |

## 变更与测试矩阵

实现涉及 `current_release.py` one-read result，`runtime/{launcher,portable,readiness,state,control,
supervisor,process,host,child,cli,error_contract}.py`，五个正式 wrappers，以及 B2/ STAB-1 测试。架构、
边界、路线、ADR 和测试索引同步为同一能力状态；`main.py` 和 gateway 无变化。

- B2 focused：`19 passed`。
- B1 + current-release/path-roots/provenance/static regressions：`430 passed, 5 skipped, 2 warnings`。
- STAB-1 lifecycle：`19 passed`。
- APP_ROOT audit tests：`7 passed, 23 deselected`；actual audit `scanned=95`、`excluded=258`、
  `detected=mapped=299`，parse/uncovered/stale/missing/invalid 均为 `0`，digest
  `464b2eef086b6fea37daf810d3b9f0551de652763f23028df799f8affb81e1ab`。
- final enterprise suite（隔离宿主插件）：`498 passed, 5 skipped, 8 warnings`；运行一次。
- `compileall enterprise tools`：exit `0`；OPS 两个直接执行型 runner：exit `0`。

skips 为既有平台条件场景；宿主 pytest 插件在原始 STAB-1 collection 中仍有既知兼容冲突，隔离插件后
STAB-1 全部通过。`github_ci_verified=false`，测试均为开发设备临时 fixture 证据。
