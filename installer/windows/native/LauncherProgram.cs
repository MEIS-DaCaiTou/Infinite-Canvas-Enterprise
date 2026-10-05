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
                var options = Core.Options(args, new[] { "--identity", "--start", "--stop", "--restart", "--status", "--health" }, new[] { "--install-root", "--result-file" });
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
        internal static Dictionary<string, object> Execute(string root, string command) {
            var install = Core.Identify(root); Core.VerifyPayload(install);
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
            state = new Label { Left = 24, Top = 24, Width = 635, Height = 75, Text = "入口固定不变。升级或回退后，将自动使用当前生效版本。关闭本窗口不停止服务。" }; Controls.Add(state);
            buttons = new FlowLayoutPanel { Left = 24, Top = 115, Width = 650, Height = 70 };
            foreach (var pair in new[] { Tuple.Create("启动并打开", "start"), Tuple.Create("停止", "stop"), Tuple.Create("重启", "restart"), Tuple.Create("查看状态", "status") }) {
                var button = new Button { Text = pair.Item1, Width = 125, Height = 38 };
                string command = pair.Item2; button.Click += async (s, e) => await Run(command); buttons.Controls.Add(button);
            }
            var export = new Button { Text = "导出诊断", Width = 105, Height = 38 };
            export.Click += (s, e) => {
                if (lastResult == null) { state.Text = "请先查看状态或执行操作，再导出诊断摘要。"; return; }
                using (var dialog = new SaveFileDialog { Filter = "诊断 ZIP|*.zip", FileName = "canvas-native-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".zip", OverwritePrompt = true }) {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    try { Core.ExportReport(dialog.FileName, lastResult); state.Text = "诊断摘要已导出；完整运行日志可在管理后台更新中心导出。"; }
                    catch (Exception exc) { state.Text = "导出未完成：" + Core.Code(exc); }
                }
            }; buttons.Controls.Add(export);
            Controls.Add(buttons);
            FormClosing += (s, e) => { if (busy) { e.Cancel = true; state.Text = "操作正在进行，请等待结果。关闭窗口不会作为停止服务的操作。"; } };
        }
        private async Task Run(string command) {
            busy = true; buttons.Enabled = false; state.Text = "正在校验当前版本并执行操作，请稍候……";
            try {
                var result = await Task.Run(() => LauncherProgram.Execute(AppDomain.CurrentDomain.BaseDirectory, command));
                lastResult = result;
                int exit = Convert.ToInt32(result["worker_exit_code"]);
                state.Text = exit == 0 ? "操作完成。" + (result.ContainsKey("state") ? "服务状态：" + result["state"] : "") + " 关闭本窗口不停止服务。" : "操作未完成，请导出诊断摘要。";
                string url = Core.BrowserUrl(result);
                if (exit == 0 && command == "start" && url != null) Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            } catch (Exception exc) { lastResult = new Dictionary<string, object> { { "result", "blocked" }, { "code", Core.Code(exc) } }; state.Text = "操作被安全阻止：" + Core.Code(exc); }
            finally { busy = false; buttons.Enabled = true; }
        }
    }
}
