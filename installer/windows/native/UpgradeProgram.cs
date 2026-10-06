using Microsoft.Win32;
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Management;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace InfiniteCanvas.Native {
    internal sealed class DiscoveryResult {
        internal readonly List<string> Roots = new List<string>();
        internal bool Complete = true;
    }
    internal static class UpgradeProgram {
        [STAThread]
        private static int Main(string[] args) {
            try {
                if (args.Length == 0) {
                    Application.EnableVisualStyles(); Application.Run(new UpgradeForm()); return 0;
                }
                var options = Core.Options(args, new[] { "--inspect", "--upgrade", "--recover-service", "--export-diagnostics", "--confirm-no-active-tasks", "--portable-entry" }, new[] { "--install-root", "--result-file" });
                if (options.ContainsKey("--export-diagnostics")) {
                    if (!options.ContainsKey("--install-root") || !options.ContainsKey("--result-file") || new[] { "--inspect", "--upgrade", "--recover-service" }.Any(options.ContainsKey)) throw Core.Block("NATIVE_ARGUMENT_INVALID");
                    var project = CollectProjectLogs(options["--install-root"]);
                    Core.ExportReport(options["--result-file"], new Dictionary<string, object> { {"result","diagnostics_exported"} }, project);
                    return Core.Text(project,"result") == "diagnostics_collected" ? 0 : 2;
                }
                if (!options.ContainsKey("--install-root") || new[] { "--inspect", "--upgrade", "--recover-service" }.Count(options.ContainsKey) != 1) throw Core.Block("NATIVE_ARGUMENT_INVALID");
                bool inspect = options.ContainsKey("--inspect");
                // Do not extract/run anything if a required confirmation is absent.
                if (!inspect && !options.ContainsKey("--confirm-no-active-tasks")) throw Core.Block("ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED");
                var result = Execute(options["--install-root"], inspect, !options.ContainsKey("--portable-entry"), options.ContainsKey("--recover-service"));
                Core.WriteResult(options.ContainsKey("--result-file") ? options["--result-file"] : null, result);
                return Success(result) ? 0 : 2;
            } catch (Exception exc) {
                var result = new Dictionary<string, object> { { "result", "blocked" }, { "code", Core.Code(exc) } };
                string path = null;
                for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--result-file") path = args[i + 1];
                try { Core.WriteResult(path, result); } catch { }
                return 2;
            }
        }
        private static byte[] Resource(string name) {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                if (stream == null || stream.Length > 100 * 1024 * 1024) throw Core.Block("NATIVE_BUNDLE_MISSING");
                using (var output = new MemoryStream()) { stream.CopyTo(output); return output.ToArray(); }
            }
        }
        internal static bool Success(Dictionary<string, object> value) {
            object result;
            return value.TryGetValue("result", out result) && new[] { "inspected", "succeeded", "already_current", "service_recovered" }.Contains(result as string);
        }
        private static Dictionary<string, Dictionary<string, object>> Catalog() {
            byte[] raw = Resource("Catalog"); Core.RequireHash(Core.Hash(raw), BuildInfo.CatalogSha);
            var records = new Dictionary<string, Dictionary<string, object>>();
            foreach (object entry in Core.List(Core.Document(raw), "sources")) {
                var row = Core.Map(entry); records.Add(Core.Text(row, "release_id"), row);
            }
            return records;
        }
        internal static InstallIdentity ApprovedInstall(string root) {
            var install = Core.Identify(root); var catalog = Catalog();
            Dictionary<string, object> approval;
            if (!catalog.TryGetValue(install.ReleaseId, out approval) || Core.Text(approval, "manifest_sha256") != install.ManifestSha)
                throw Core.Block("NATIVE_UPGRADE_SOURCE_UNSUPPORTED");
            Core.RequireHash(Core.HashFile(install.Python), Core.Text(approval, "python_sha256"));
            return install;
        }
        private static string ExtractBundle() {
            byte[] bytes = Resource("Bundle"); Core.RequireHash(Core.Hash(bytes), BuildInfo.BundleSha);
            var index = Core.Document(Resource("BundleIndex"));
            var expected = Core.List(index, "files").Select(Core.Map).ToDictionary(x => Core.Text(x, "path"), StringComparer.Ordinal);
            string parent = Path.Combine(Path.GetTempPath(), @"ICE\U"); Core.SafePath(parent, true); Directory.CreateDirectory(parent); Core.SafePath(parent, false);
            string root = Path.Combine(parent, Guid.NewGuid().ToString("N").Substring(0, 12)); Directory.CreateDirectory(root);
            try {
            using (var archive = new ZipArchive(new MemoryStream(bytes), ZipArchiveMode.Read)) {
                if (archive.Entries.Count != expected.Count) throw Core.Block("NATIVE_BUNDLE_INVALID");
                foreach (var entry in archive.Entries) {
                    Dictionary<string, object> item;
                    if (!expected.TryGetValue(entry.FullName, out item) || entry.Length != Convert.ToInt64(item["size_bytes"])) throw Core.Block("NATIVE_BUNDLE_INVALID");
                    string path = Core.Under(root, entry.FullName, true);
                    Directory.CreateDirectory(Path.GetDirectoryName(path)); Core.SafePath(path, true);
                    using (var source = entry.Open())
                    using (var target = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { source.CopyTo(target); }
                    Core.RequireHash(Core.HashFile(path), Core.Text(item, "sha256")); expected.Remove(entry.FullName);
                }
            }
            return root;
            } catch { CleanBundle(root); throw; }
        }
        private static void CleanBundle(string root) {
            // Delete only unchanged files from this invocation's pinned
            // resource index, then empty directories. Never recursively remove
            // a selected installation or a user-owned tree.
            try {
                string parent = Path.GetFullPath(Path.Combine(Path.GetTempPath(), @"ICE\U"));
                if (Path.GetDirectoryName(root) != parent || !System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(root), @"\A[0-9a-f]{12}\z")) return;
                Core.SafePath(root, false);
                var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { root };
                foreach (object entry in Core.List(Core.Document(Resource("BundleIndex")), "files")) {
                    var item = Core.Map(entry); string path = Core.Under(root, Core.Text(item, "path"), true);
                    if (File.Exists(path) && Core.HashFile(path) == Core.Text(item, "sha256")) File.Delete(path);
                    string current = Path.GetDirectoryName(path);
                    while (current != root && current != null) { directories.Add(current); current = Path.GetDirectoryName(current); }
                }
                foreach (string directory in directories.OrderByDescending(x => x.Length)) {
                    Core.SafePath(directory, true);
                    if (Directory.Exists(directory) && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory, false);
                }
            } catch { } // Leave a changed/unverified file intact for investigation.
        }
        internal static Dictionary<string, object> Execute(string root, bool inspect, bool registerEntry = true, bool recoverService = false) {
            if (inspect && recoverService) throw Core.Block("NATIVE_ARGUMENT_INVALID");
            var install = ApprovedInstall(root); Core.VerifyPayload(install);
            if (!inspect && !recoverService && install.Root.TrimEnd('\\').Length + 1 + BuildInfo.TargetSuffixLength > 240) throw Core.Block("NATIVE_LEGACY_PATH_TOO_LONG");
            string bundle = ExtractBundle();
            try {
                var args = new List<string> {
                "--install-root", install.Root, "--catalog", Core.Under(bundle, "catalog.json"),
                "--manifest", Core.Under(bundle, "core/ops-release-manifest-v2.json"),
                "--archive", Core.Under(bundle, "core/release.zip"),
                "--inventory", Core.Under(bundle, "core/release-payload-inventory.json"),
                inspect ? "--inspect-only" : "--confirm-no-active-tasks",
            };
                if (recoverService) args.Add("--recover-service-only");
                var result = Core.RunPython(install, Core.Under(bundle, "engine/tools/unified_upgrade.py"), args);
                if (!inspect && !recoverService && Success(result)) {
                // Entry installation is a separate outcome. Never misreport a
                // committed healthy upgrade as failed and invite a paid retry.
                    try { PublishEntry(install.Root, Core.Under(bundle, "InfiniteCanvas.exe"), registerEntry); result["launcher_installed"] = true; }
                    catch (Exception exc) { result["launcher_installed"] = false; result["launcher_code"] = Core.Code(exc); }
                }
                return result;
            } finally { CleanBundle(bundle); }
        }
        internal static Dictionary<string, object> CollectProjectLogs(string root) {
            try {
                var install = ApprovedInstall(root); Core.VerifyPayload(install);
                string bundle = ExtractBundle();
                try {
                    return Core.RunPython(install, Core.Under(bundle,"engine/tools/unified_upgrade.py"), new[] {
                        "--install-root",install.Root,"--catalog",Core.Under(bundle,"catalog.json"),
                        "--manifest",Core.Under(bundle,"core/ops-release-manifest-v2.json"),
                        "--archive",Core.Under(bundle,"core/release.zip"),
                        "--inventory",Core.Under(bundle,"core/release-payload-inventory.json"),"--diagnostics-only"
                    }, 2 * 1024 * 1024);
                } finally { CleanBundle(bundle); }
            } catch (Exception exc) { return new Dictionary<string, object> { {"result","diagnostics_unavailable"}, {"code",Core.Code(exc)} }; }
        }
        private static void PublishEntry(string root, string source, bool registerEntry) {
            string target = Path.Combine(root, "InfiniteCanvas.exe"), record = Path.Combine(root, @"state\native-entry.json");
            Core.SafePath(target, true); Core.SafePath(record, true);
            string sha = Core.HashFile(source);
            bool identical = File.Exists(target) && Core.HashFile(target) == sha;
            if (File.Exists(target) && !identical) {
                if (!File.Exists(record)) throw Core.Block("NATIVE_ENTRY_UNOWNED_FILE");
                var previous = Core.ReadJson(record, 16384);
                if (Core.Text(previous, "schema_version") != "enterprise-native-entry-v1" || Core.Text(previous, "launcher_sha256") != Core.HashFile(target))
                    throw Core.Block("NATIVE_ENTRY_UNOWNED_FILE");
            }
            string suffix = Guid.NewGuid().ToString("N"), temporary = target + "." + suffix + ".new";
            if (!identical) {
                using (var input = File.OpenRead(source))
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { input.CopyTo(output); output.Flush(true); }
                try {
                    if (File.Exists(target)) {
                        string backup = Path.Combine(root, @"state\native-entry-backups"); Core.SafePath(backup, true); Directory.CreateDirectory(backup);
                        File.Replace(temporary, target, Path.Combine(backup, suffix + ".exe"));
                    } else File.Move(temporary, target);
                } finally { if (File.Exists(temporary) && Core.HashFile(temporary) == sha) File.Delete(temporary); }
            }
            var metadata = new Dictionary<string, object> { { "schema_version", "enterprise-native-entry-v1" }, { "launcher_sha256", sha } };
            string recordTemporary = record + "." + suffix + ".new"; Core.WriteResult(recordTemporary, metadata);
            if (File.Exists(record)) File.Replace(recordTemporary, record, null); else File.Move(recordTemporary, record);
            if (!registerEntry) return; // Portable mode: no registry or desktop writes.
            using (var registry = Registry.CurrentUser.CreateSubKey(Core.ProductRegistry + "\\" + Core.Hash(Encoding.UTF8.GetBytes(root.ToLowerInvariant())).Substring(0, 24))) {
                registry.SetValue("InstallLocation", root); registry.SetValue("Launcher", target);
            }
            var shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            object link = null;
            try {
            string name = "无限画布企业版（" + Path.GetFileName(root.TrimEnd('\\')) + "）.lnk";
            string linkPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), name);
            Core.SafePath(linkPath, true);
            link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { linkPath });
            string oldTarget = (string)link.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
            if (File.Exists(linkPath) && !String.Equals(oldTarget, target, StringComparison.OrdinalIgnoreCase)) throw Core.Block("NATIVE_SHORTCUT_UNOWNED_FILE");
            link.GetType().InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { target });
            link.GetType().InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { root });
            link.GetType().InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "固定入口：自动使用当前生效版本" });
            link.GetType().InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            } finally {
                if (link != null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            }
        }
        internal static DiscoveryResult Discover() {
            var discovery = new DiscoveryResult();
            var hints = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            Action<string> add = value => {
                if (String.IsNullOrWhiteSpace(value)) return;
                if (hints.Count >= 64) { discovery.Complete = false; return; }
                try { var install = ApprovedInstall(value); hints.Add(install.Root); } catch { }
            };
            foreach (RegistryKey hive in new[] { Registry.CurrentUser, Registry.LocalMachine }) {
                try { using (var key = hive.OpenSubKey(Core.ProductRegistry)) {
                    if (key == null) continue;
                    string[] names = key.GetSubKeyNames(); if (names.Length > 32) discovery.Complete = false;
                    foreach (string name in names.Take(32)) using (var item = key.OpenSubKey(name)) add(item == null ? null : item.GetValue("InstallLocation") as string);
                } } catch { discovery.Complete = false; }
            }
            string near = AppDomain.CurrentDomain.BaseDirectory;
            for (int i = 0; i < 4 && near != null; i++, near = Path.GetDirectoryName(near.TrimEnd('\\'))) add(near);
            try {
                using (var query = new ManagementObjectSearcher("SELECT ExecutablePath FROM Win32_Process WHERE Name='python.exe'"))
                using (var processes = query.Get()) {
                    if (processes.Count > 64) discovery.Complete = false;
                    foreach (ManagementObject process in processes.Cast<ManagementObject>().Take(64)) {
                        using (process) {
                            string path = process["ExecutablePath"] as string;
                            if (path == null) continue;
                            DirectoryInfo python = new FileInfo(path).Directory;
                            if (python != null && python.Name == "python" && python.Parent != null && python.Parent.Parent != null && python.Parent.Parent.Name == "releases")
                                add(python.Parent.Parent.Parent.FullName);
                        }
                    }
                }
            } catch { discovery.Complete = false; }
            object shell = null;
            try {
                shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
                foreach (string directory in new[] { Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Environment.GetFolderPath(Environment.SpecialFolder.Programs) }) {
                    Core.SafePath(directory, false);
                    string[] links = Directory.EnumerateFiles(directory, "无限画布企业版*.lnk", SearchOption.TopDirectoryOnly).Take(17).ToArray();
                    if (links.Length > 16) discovery.Complete = false;
                    foreach (string path in links.Take(16)) {
                        Core.SafePath(path, false);
                        object link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
                        try {
                            string target = (string)link.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
                            string candidate = Path.GetDirectoryName(target);
                            for (int i = 0; i < 4 && candidate != null; i++, candidate = Path.GetDirectoryName(candidate.TrimEnd('\\'))) add(candidate);
                        } finally { System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link); }
                    }
                }
            } catch { discovery.Complete = false; }
            finally { if (shell != null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell); }
            // No drive scan, process command line, credential read or fallback
            // to a different root after a user's explicit selection.
            discovery.Roots.AddRange(hints.OrderBy(x => x, StringComparer.OrdinalIgnoreCase)); return discovery;
        }
    }
    internal sealed class UpgradeForm : Form {
        private readonly ComboBox locations;
        private readonly Label state;
        private readonly CheckBox confirmed;
        private readonly Button inspect, upgrade, browse, export, recover;
        private readonly ProgressBar progress;
        private bool busy;
        private Dictionary<string, object> lastResult;
        internal UpgradeForm() {
            Text = "无限画布企业版 — 通用升级与固定入口"; ClientSize = new Size(660, 320);
            Font = new Font("Microsoft YaHei UI", 10); StartPosition = FormStartPosition.CenterScreen; MaximizeBox = false; FormBorderStyle = FormBorderStyle.FixedDialog;
            Controls.Add(new Label { Left = 22, Top = 20, Width = 615, Height = 45, Text = "选择已有安装，统一升级到 " + BuildInfo.TargetVersion + "。校验版本与数据库，失败时恢复，不创建重复安装。" });
            locations = new ComboBox { Left = 24, Top = 75, Width = 490, DropDownStyle = ComboBoxStyle.DropDown };
            browse = new Button { Left = 527, Top = 73, Width = 110, Height = 32, Text = "浏览目录" };
            browse.Click += (s, e) => { using (var dialog = new FolderBrowserDialog()) if (dialog.ShowDialog(this) == DialogResult.OK) locations.Text = dialog.SelectedPath; };
            confirmed = new CheckBox { Left = 24, Top = 123, Width = 610, Text = "我已确认没有未完成的 AI 任务；允许暂停服务并执行恢复或升级。" };
            state = new Label { Left = 24, Top = 170, Width = 610, Height = 64, Text = "请先检查安装。成功后将在根目录安装固定的 InfiniteCanvas.exe，并创建桌面快捷方式。" };
            inspect = new Button { Left = 24, Top = 260, Width = 145, Height = 35, Text = "只读检查" };
            upgrade = new Button { Left = 480, Top = 260, Width = 156, Height = 35, Text = "确认并升级" };
            progress = new ProgressBar { Left = 24, Top = 235, Width = 612, Height = 8, Visible = false, Style = ProgressBarStyle.Marquee };
            export = new Button { Left = 185, Top = 260, Width = 130, Height = 35, Text = "导出诊断日志" };
            recover = new Button { Left = 330, Top = 260, Width = 138, Height = 35, Text = "恢复当前服务" };
            export.Click += async (s, e) => {
                string root = locations.Text;
                var operation = lastResult ?? new Dictionary<string, object> { {"result","not_run"} };
                using (var dialog = new SaveFileDialog { Filter = "诊断 ZIP|*.zip", FileName = "canvas-upgrade-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".zip", OverwritePrompt = true }) {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    busy = true; locations.Enabled = browse.Enabled = inspect.Enabled = upgrade.Enabled = confirmed.Enabled = export.Enabled = recover.Enabled = false; progress.Visible = true;
                    state.Text = "正在只读收集工具阶段和脱敏 Runtime／更新日志，不更改版本或业务数据……";
                    try {
                        var project = await Task.Run(() => UpgradeProgram.CollectProjectLogs(root));
                        Core.ExportReport(dialog.FileName, operation, project);
                        state.Text = Core.Text(project,"result") == "diagnostics_collected" ? "已导出工具阶段及脱敏项目日志；有范围和大小上限。请检查业务信息后发送 ZIP。" : "已导出工具摘要；项目日志未收集：" + Core.Text(project,"code") + "。不会运行无法核验的安装。";
                    }
                    catch (Exception exc) { state.Text = "导出未完成：" + Core.Code(exc); }
                    finally { busy = false; progress.Visible = false; locations.Enabled = browse.Enabled = inspect.Enabled = upgrade.Enabled = confirmed.Enabled = export.Enabled = recover.Enabled = true; }
                }
            };
            Controls.AddRange(new Control[] { locations, browse, confirmed, state, inspect, upgrade, progress, export, recover });
            inspect.Click += async (s, e) => await Run(true); upgrade.Click += async (s, e) => await Run(false);
            recover.Click += async (s, e) => {
                if (MessageBox.Show(this, "仅恢复所选安装的当前版本服务；不升级、不迁移数据库、不更改画布和素材。确认无活动 AI 任务后继续？", "恢复当前服务", MessageBoxButtons.OKCancel) == DialogResult.OK) await Run(false, true);
            };
            FormClosing += (s, e) => { if (busy) { e.Cancel = true; state.Text = "操作正在进行。请等待升级与恢复结果，不要关闭窗口。"; } };
            Shown += async (s, e) => {
                var result = await Task.Run(() => UpgradeProgram.Discover());
                if (IsDisposed || Disposing) return;
                locations.Items.AddRange(result.Roots.Cast<object>().ToArray());
                if (result.Roots.Count == 1 && result.Complete && String.IsNullOrWhiteSpace(locations.Text)) locations.SelectedIndex = 0;
                else if (!result.Complete) state.Text = "自动定位未完整完成，请手动确认已有安装目录，不会替你创建新安装。";
                else if (result.Roots.Count > 1) state.Text = "检测到多个安装，请明确选择。工具不会自动操作其他目录。";
            };
        }
        private async Task Run(bool readOnly, bool recoverService = false) {
            if (String.IsNullOrWhiteSpace(locations.Text)) { state.Text = "请明确选择已有安装目录。"; return; }
            if (!readOnly && !confirmed.Checked) { state.Text = "请先完成无活动任务确认。"; return; }
            string root = locations.Text; busy = true; locations.Enabled = browse.Enabled = inspect.Enabled = upgrade.Enabled = confirmed.Enabled = export.Enabled = recover.Enabled = false; progress.Visible = true;
            state.Text = readOnly ? "正在只读核验版本、完整文件和数据库……" : recoverService ? "正在核验并受控停止、启动当前版本；不会迁移数据库或切换版本。" : "正在校验、准备、保护数据、切换与检查结果；失败时自动回退。";
            try {
                var result = await Task.Run(() => UpgradeProgram.Execute(root, readOnly, true, recoverService));
                lastResult = result;
                string resultName = Core.Text(result, "result");
                if (resultName == "inspected") state.Text = "检查通过：" + Core.Text(result, "source_version") + "；数据库状态：" + Core.Text(result, "database_variant") + "。";
                else if (resultName == "service_recovered") state.Text = "当前版本服务已恢复，版本和业务数据未切换。请打开原网页地址验收登录与已有画布。";
                else if (UpgradeProgram.Success(result)) state.Text = "升级成功／已是目标版本。" + (result.ContainsKey("launcher_installed") && (bool)result["launcher_installed"] ? "今后使用桌面固定入口启停。" : "固定入口安装需处理：" + Core.Text(result, "launcher_code"));
                else state.Text = "操作未完成：" + (result.ContainsKey("result_code") ? Core.Text(result, "result_code") : Core.Text(result, "code")) + "；原服务恢复：" + (Core.Text(result, "source_recovery") == "healthy" ? "已恢复" : "未确认") + "。请导出诊断，不要反复重试。";
            } catch (Exception exc) { lastResult = new Dictionary<string, object> { { "result", "blocked" }, { "code", Core.Code(exc) } }; state.Text = "操作被安全阻止：" + Core.Code(exc); }
            finally { busy = false; progress.Visible = false; locations.Enabled = browse.Enabled = inspect.Enabled = upgrade.Enabled = confirmed.Enabled = export.Enabled = recover.Enabled = true; }
        }
    }
}
