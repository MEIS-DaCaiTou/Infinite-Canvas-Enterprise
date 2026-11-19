using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace InfiniteCanvas.Native {
    internal static class LauncherProgram {
        [STAThread]
        private static int Main(string[] args) {
            try {
                if (args.Length == 0) {
                    Application.EnableVisualStyles(); Application.Run(new LauncherForm()); return 0;
                }
                if (args[0] == "--export-diagnostics") {
                    var diagnosticOptions = Core.Options(args, new[] { "--export-diagnostics" },
                        new[] { "--install-root", "--archive-file", "--setup-log", "--setup-code" });
                    var operation = new Dictionary<string, object>();
                    string value, setupLog;
                    if (diagnosticOptions.TryGetValue("--setup-code", out value)) operation["code"] = value;
                    diagnosticOptions.TryGetValue("--setup-log", out setupLog);
                    string installRoot = diagnosticOptions.TryGetValue("--install-root", out value)
                        ? value : AppDomain.CurrentDomain.BaseDirectory;
                    NativeDiagnostics.Export(diagnosticOptions["--archive-file"], installRoot, operation, setupLog);
                    return 0;
                }
                var options = Core.Options(args, new[] { "--identity", "--tool-info", "--start", "--stop", "--restart", "--status", "--health" }, new[] { "--install-root", "--result-file" });
                var command = options.Keys.Where(k => k != "--install-root" && k != "--result-file").ToArray();
                if (command.Length != 1) throw Core.Block("NATIVE_ARGUMENT_INVALID");
                string root = options.ContainsKey("--install-root") ? options["--install-root"] : AppDomain.CurrentDomain.BaseDirectory;
                var result = Execute(root, command[0].Substring(2));
                Core.WriteResult(options.ContainsKey("--result-file") ? options["--result-file"] : null, result);
                return result.ContainsKey("worker_exit_code") ? Convert.ToInt32(result["worker_exit_code"]) : 0;
            } catch (Exception exc) {
                // CLI failures deliberately never display a blocking dialog.
                var result = new Dictionary<string, object> { { "result", "blocked" }, { "code", Core.Code(exc) } };
                string path = null;
                for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--result-file") path = args[i + 1];
                try { Core.WriteResult(path, result); } catch { }
                return 2;
            }
        }
        internal static Dictionary<string, object> Execute(string root, string command, bool quickStatus = false) {
            if (command == "stop" || (command == "status" && quickStatus)) {
                using (var mailbox = RuntimeMailbox.Observe(root, command == "stop")) {
                    if (mailbox != null) return command == "stop" ? mailbox.Stop() : mailbox.Status();
                }
            }
            InstallIdentity install;
            try {
                install = Core.Identify(root);
                Core.VerifyPayload(install);
            } catch (Exception exc) when (command == "status" && !quickStatus) {
                // Preserve detailed CLI status on healthy installations. On a
                // damaged copy expose the running instance without loading Python.
                using (var mailbox = RuntimeMailbox.Observe(root, false)) {
                    if (mailbox == null) throw;
                    var result = mailbox.Status();
                    result["release_integrity_code"] = Core.Code(exc);
                    return result;
                }
            }
            if (command == "tool-info") return new Dictionary<string, object> { { "result", "verified" }, { "native_tool_contract", 2 }, { "release_id", install.ReleaseId } };
            if (command == "identity") return new Dictionary<string, object> { { "result", "verified" }, { "release_id", install.ReleaseId }, { "manifest_sha256", install.ManifestSha } };
            if (!new[] { "start", "stop", "restart", "status", "health" }.Contains(command)) throw Core.Block("NATIVE_COMMAND_INVALID");
            return Core.RunPython(install, Core.Under(install.AppRoot, "enterprise/runtime/launcher.py"), new[] { "portable", command });
        }
    }
    internal sealed class LauncherForm : Form {
        private readonly Label state;
        private readonly FlowLayoutPanel buttons;
        private Dictionary<string, object> lastResult;
        private bool busy;
        internal LauncherForm() {
            Text = "无限画布企业版"; ClientSize = new Size(680, 210); StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 10); FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
            state = new Label { Left = 24, Top = 24, Width = 635, Height = 75, Text = "点击“启动并打开”即可使用当前已安装版本，不会自动更新。更新由管理员在管理后台更新中心单独确认；关闭本窗口不停止服务。在线更新受阻时，先查看状态，必要时停止服务后运行目标版本维护安装器。" }; Controls.Add(state);
            buttons = new FlowLayoutPanel { Left = 24, Top = 115, Width = 650, Height = 70 };
            foreach (var pair in new[] { Tuple.Create("启动并打开", "start"), Tuple.Create("停止", "stop"), Tuple.Create("重启", "restart"), Tuple.Create("查看状态", "status") }) {
                var button = new Button { Text = pair.Item1, Width = 125, Height = 38 };
                string command = pair.Item2; button.Click += async (s, e) => await Run(command); buttons.Controls.Add(button);
            }
            var export = new Button { Text = "导出诊断", Width = 105, Height = 38 };
            export.Click += async (s, e) => {
                using (var dialog = new SaveFileDialog { Filter = "诊断 ZIP|*.zip", FileName = "canvas-native-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".zip", OverwritePrompt = true }) {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    busy = true; buttons.Enabled = false;
                    var operation = lastResult ?? new Dictionary<string, object>();
                    string path = dialog.FileName;
                    try {
                        await Task.Run(() => NativeDiagnostics.Export(path, AppDomain.CurrentDomain.BaseDirectory, operation));
                        state.Text = "故障诊断 ZIP 已保存。可将整个文件交给维护人员。";
                    }
                    catch (Exception exc) { state.Text = "导出未完成：" + Core.Code(exc); }
                    finally { busy = false; buttons.Enabled = true; }
                }
            }; buttons.Controls.Add(export);
            Controls.Add(buttons);
            FormClosing += (s, e) => { if (busy) { e.Cancel = true; state.Text = "操作正在进行，请等待结果。关闭窗口不会作为停止服务的操作。"; } };
        }
        private async Task Run(string command) {
            busy = true; buttons.Enabled = false; state.Text = "正在处理，请稍候……";
            try {
                var result = await Task.Run(() => LauncherProgram.Execute(AppDomain.CurrentDomain.BaseDirectory, command, quickStatus: true));
                lastResult = result;
                int exit = Convert.ToInt32(result["worker_exit_code"]);
                state.Text = exit == 0 ? "操作完成。" + (result.ContainsKey("state") ? "服务状态：" + result["state"] : "") + " 关闭本窗口不停止服务。" :
                    "操作未完成。" + (result.ContainsKey("code") ? "错误代码：" + result["code"] + "。" : "") + "请导出故障诊断 ZIP。";
                if (exit == 0 && command == "status" && result.ContainsKey("inspection_source"))
                    state.Text = "已识别当前服务实例。服务状态为 " + result["state"] + "。程序完整性在启动和重启时校验。";
                string url = Core.BrowserUrl(result);
                if (exit == 0 && command == "start" && url != null) Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            } catch (Exception exc) { lastResult = new Dictionary<string, object> { { "result", "blocked" }, { "code", Core.Code(exc) } }; state.Text = "操作被安全阻止：" + Core.Code(exc); }
            finally { busy = false; buttons.Enabled = true; }
        }
    }
}
