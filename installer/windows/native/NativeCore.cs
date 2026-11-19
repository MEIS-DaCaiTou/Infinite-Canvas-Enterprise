// Thin Windows presentation/bootstrap layer. Lifecycle and DATA remain Python.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

namespace InfiniteCanvas.Native {
    internal sealed class InstallIdentity {
        internal string Root, AppRoot, ReleaseId, ManifestSha, Python;
    }

    // Client for the supervisor's existing control mailbox. It never loads code
    // from the installation to inspect or stop an already running instance.
    internal sealed class RuntimeMailbox : IDisposable {
        private const string Schema = "runtime-supervisor-state-v1";
        private const uint WaitTimeout = 258;
        private static readonly Regex InstanceId = new Regex(@"\A[0-9a-f]{16,64}\z");
        private static readonly Regex RequestId = new Regex(@"\A[0-9a-f]{32}\z");
        private readonly string runtimeRoot, releaseId, instanceId, contextIdentity;
        private readonly Dictionary<string, object> state;
        private readonly SafeWaitHandle host;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern SafeWaitHandle OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetProcessTimes(SafeWaitHandle process, out long created,
            out long exited, out long kernel, out long user);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool QueryFullProcessImageName(SafeWaitHandle process, int flags, StringBuilder path, ref int length);
        [DllImport("kernel32.dll")]
        private static extern uint WaitForSingleObject(SafeWaitHandle handle, uint milliseconds);

        private RuntimeMailbox(string runtimeRoot, string releaseId, string instanceId, string contextIdentity,
                               Dictionary<string, object> state, SafeWaitHandle host) {
            this.runtimeRoot = runtimeRoot;
            this.releaseId = releaseId;
            this.instanceId = instanceId;
            this.contextIdentity = contextIdentity;
            this.state = state;
            this.host = host;
        }

        private static object Value(Dictionary<string, object> record, string key) {
            object value;
            return record.TryGetValue(key, out value) ? value : null;
        }
        private static long Number(Dictionary<string, object> record, string key) {
            object value = Value(record, key);
            return value is int || value is long ? Convert.ToInt64(value) : -1;
        }
        private static bool SameImage(string expected, string reported) {
            if (reported == null) return false;
            if (reported.StartsWith(@"\\?\", StringComparison.Ordinal)) reported = reported.Substring(4);
            return String.Equals(expected, reported, StringComparison.OrdinalIgnoreCase);
        }

        internal static RuntimeMailbox Observe(string installRoot, bool forStop) {
            try {
                var root = Path.GetFullPath(installRoot);
                Core.SafePath(root, false);
                if (forStop && new[] { "system-update-active.lock", "install-upgrade-active.json",
                                       "upgrade-sequence-active.json", "install-mvp-active.lock" }
                    .Any(marker => File.Exists(Core.Under(root, "state/" + marker, true)))) return null;
                var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (String.IsNullOrEmpty(local)) return null;
                var runtime = Core.Under(local, "InfiniteCanvasEnterprise/runtime", true);
                var contextPath = Core.Under(runtime, "launch-context.json", true);
                var lockPath = Core.Under(runtime, "runtime-supervisor.lock", true);
                var statePath = Core.Under(runtime, "runtime-state.json", true);
                if (!File.Exists(contextPath) || !File.Exists(lockPath) || !File.Exists(statePath)) return null;

                var raw = Core.ReadBytes(contextPath, 16384);
                var context = Core.Document(raw);
                var identity = Core.Hash(raw);  // Same canonical launch-context bytes the supervisor binds.
                var release = Core.Text(context, "release_id");
                var instance = Core.Text(context, "instance_id");
                if (Core.Text(context, "schema_version") != "env-1b1c-runtime-launch-context-v2"
                    || !Core.Component.IsMatch(release) || !InstanceId.IsMatch(instance)
                    || Core.Text(context, "app_root_relative") != "releases/" + release) return null;

                var expected = Core.Under(root, "releases/" + release + "/python/python.exe", true);
                var state = Core.ReadJson(statePath, 65536);
                var runtimeLock = Core.ReadJson(lockPath, 65536);
                if (!Equals(Value(runtimeLock, "lock_phase"), "adopted")) return null;
                var pid = Number(state, "supervisor_pid");
                var created = Number(state, "supervisor_process_created_at");
                if (pid < 1 || pid > Int32.MaxValue || created <= 0 || Number(state, "state_generation") < 0) return null;
                foreach (var record in new[] { state, runtimeLock }) {
                    if (!Equals(Value(record, "schema_version"), Schema)
                        || !Equals(Value(record, "runtime_mode"), "portable-release")
                        || !Equals(Value(record, "supervisor_instance_id"), instance)
                        || !Equals(Value(record, "release_id"), release)
                        || !Equals(Value(record, "launch_context_identity"), identity)
                        || Number(record, "supervisor_pid") != pid || Number(record, "supervisor_process_created_at") != created
                        || !SameImage(expected, Value(record, "supervisor_executable") as string)) return null;
                }
                var process = OpenProcess(0x101000, false, (int)pid);  // SYNCHRONIZE | QUERY_LIMITED_INFORMATION.
                var image = new StringBuilder(32768);
                var length = image.Capacity;
                long start, exited, kernel, user;
                if (process.IsInvalid || !GetProcessTimes(process, out start, out exited, out kernel, out user)
                    || start != created || !QueryFullProcessImageName(process, 0, image, ref length)
                    || !SameImage(expected, image.ToString()) || WaitForSingleObject(process, 0) != WaitTimeout) {
                    process.Dispose();
                    return null;
                }
                return new RuntimeMailbox(runtime, release, instance, identity, state, process);
            } catch (IOException) { return null; }
              catch (UnauthorizedAccessException) { return null; }
              catch (InvalidOperationException) { return null; }
              catch (ArgumentException) { return null; }
        }

        internal Dictionary<string, object> Status() {
            return new Dictionary<string, object> {
                { "result", "observed" }, { "state", Value(state, "state") }, { "running_release_id", releaseId },
                { "inspection_source", "supervisor_mailbox" }, { "worker_exit_code", 0 }
            };
        }

        internal Dictionary<string, object> Stop() {
            var control = Core.Under(runtimeRoot, "control");
            var request = Value(state, "active_control_request_id") as string;
            if (!Equals(Value(state, "active_control_command"), "stop") || request == null || !RequestId.IsMatch(request)) {
                if (WaitForSingleObject(host, 0) != WaitTimeout) throw Core.Block("NATIVE_RUNTIME_OWNERSHIP_CHANGED");
                request = Guid.NewGuid().ToString("N");
                var path = Core.Under(control, "cmd-" + request.Substring(0, 16) + ".json", true);
                var temporary = Core.Under(control, "native-" + request + ".tmp", true);
                Core.WriteResult(temporary, new Dictionary<string, object> {
                    { "schema_version", Schema }, { "request_id", request }, { "command", "stop" },
                    { "supervisor_instance_id", instanceId }, { "issued_at", DateTime.UtcNow.ToString("o") },
                    { "expected_state_generation", Number(state, "state_generation") },
                    { "launch_context_identity", contextIdentity }
                });
                try { File.Move(temporary, path); }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
            var ackPath = Core.Under(control, "ack-" + request.Substring(0, 16) + ".json", true);
            var timer = Stopwatch.StartNew();
            while (timer.ElapsedMilliseconds < 60000) {
                Core.SafePath(ackPath, true);
                if (File.Exists(ackPath)) {
                    var ack = Core.ReadJson(ackPath, 65536);
                    if (!Equals(Value(ack, "schema_version"), Schema)
                        || !Equals(Value(ack, "command"), "stop") || !Equals(Value(ack, "request_id"), request)
                        || !Equals(Value(ack, "supervisor_instance_id"), instanceId)
                        || !Equals(Value(ack, "launch_context_identity"), contextIdentity))
                        throw Core.Block("NATIVE_RUNTIME_ACK_UNTRUSTED");
                    var result = Core.Text(ack, "result");
                    if (result != "stopped" || WaitForSingleObject(host, 0) == 0) {
                        var outcome = Status();
                        outcome["result"] = result;
                        outcome["worker_exit_code"] = result == "stopped" ? 0 : 2;
                        if (result == "stopped") {
                            outcome["state"] = "stopped";
                            ack["supervisor_exit_confirmed"] = true;
                        }
                        outcome["ack"] = ack;
                        return outcome;
                    }
                }
                Thread.Sleep(200);
            }
            throw Core.Block("NATIVE_RUNTIME_STOP_UNCONFIRMED");
        }

        public void Dispose() { host.Dispose(); }
    }

    internal static class Core {
        internal const string ProductRegistry = @"Software\Infinite-Canvas-Enterprise\Installations";
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024, RecursionLimit = 64 };
        internal static readonly Regex Digest = new Regex(@"\A[0-9a-f]{64}\z");
        internal static readonly Regex Component = new Regex(@"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z");
        internal static Exception Block(string code) { return new InvalidOperationException(code); }
        internal static string Code(Exception exc) {
            string text = exc.Message;
            return Regex.IsMatch(text, @"\A[A-Z0-9_]{1,100}\z") ? text : "NATIVE_OPERATION_FAILED";
        }
        internal static string Hash(byte[] bytes) {
            using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        internal static string HashFile(string path) {
            SafePath(path, false);
            using (var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(source)).Replace("-", "").ToLowerInvariant();
        }
        internal static void SafePath(string path, bool allowMissing) {
            string full = Path.GetFullPath(path);
            if (!Path.IsPathRooted(path) || full.StartsWith(@"\\", StringComparison.Ordinal) || full.Length <= 3)
                throw Block("NATIVE_PATH_INVALID");
            if (new DriveInfo(Path.GetPathRoot(full)).DriveType != DriveType.Fixed) throw Block("NATIVE_PATH_NOT_LOCAL");
            string item = full;
            bool missing = false;
            while (item != null) {
                try {
                    if ((File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0) throw Block("NATIVE_PATH_UNSAFE");
                } catch (FileNotFoundException) { missing = true; }
                  catch (DirectoryNotFoundException) { missing = true; }
                item = Path.GetDirectoryName(item);
            }
            if (missing && !allowMissing) throw Block("NATIVE_PATH_MISSING");
        }
        internal static string Under(string root, string relative, bool allowMissing = false) {
            if (String.IsNullOrEmpty(relative) || Path.IsPathRooted(relative) || relative.Contains(":") || relative.Contains("\\") ||
                relative.Split('/').Any(p => p == ".." || p == "." || p.Length == 0)) throw Block("NATIVE_RELATIVE_PATH_INVALID");
            string result = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!result.StartsWith(Path.GetFullPath(root).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))
                throw Block("NATIVE_PATH_ESCAPE");
            SafePath(result, allowMissing);
            return result;
        }
        internal static byte[] ReadBytes(string path, int limit) {
            SafePath(path, false);
            using (var handle = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                if (handle.Length <= 0 || handle.Length > limit) throw Block("NATIVE_JSON_SIZE_INVALID");
                var bytes = new byte[(int)handle.Length];
                int read = 0;
                while (read < bytes.Length) {
                    int count = handle.Read(bytes, read, bytes.Length - read);
                    if (count == 0) throw Block("NATIVE_JSON_READ_FAILED");
                    read += count;
                }
                return bytes;
            }
        }
        internal static Dictionary<string, object> Document(byte[] raw) {
            return Map(Json.DeserializeObject(new UTF8Encoding(false, true).GetString(raw)));
        }
        internal static Dictionary<string, object> ReadJson(string path, int limit) { return Document(ReadBytes(path, limit)); }
        internal static Dictionary<string, object> Map(object value) {
            var result = value as Dictionary<string, object>;
            if (result == null) throw Block("NATIVE_JSON_INVALID");
            return result;
        }
        internal static string Text(Dictionary<string, object> value, string key) {
            object result;
            if (!value.TryGetValue(key, out result) || !(result is string)) throw Block("NATIVE_JSON_INVALID");
            return (string)result;
        }
        internal static object[] List(Dictionary<string, object> value, string key) {
            object result;
            if (!value.TryGetValue(key, out result) || !(result is object[])) throw Block("NATIVE_JSON_INVALID");
            return (object[])result;
        }
        internal static void RequireHash(string actual, string expected) {
            if (!Digest.IsMatch(expected) || actual != expected) throw Block("NATIVE_FILE_IDENTITY_MISMATCH");
        }
        internal static InstallIdentity Identify(string root) {
            root = Path.GetFullPath(root);
            SafePath(root, false);
            string pointerPath = Path.Combine(root, @"state\current-release.json");
            byte[] pointerBytes = ReadBytes(pointerPath, 16384);
            string raw = new UTF8Encoding(false, true).GetString(pointerBytes);
            var pointer = Document(pointerBytes);
            string[] fields = { "schema_version", "release_id", "app_root_relative", "manifest_sha256", "activated_at", "previous_release_id" };
            if (pointer.Count != fields.Length || fields.Any(k => !pointer.ContainsKey(k) || Regex.Matches(raw, "\"" + k + "\"\\s*:").Count != 1))
                throw Block("NATIVE_CURRENT_RELEASE_INVALID");
            string id = Text(pointer, "release_id"), sha = Text(pointer, "manifest_sha256");
            if (Text(pointer, "schema_version") != "env-1b1b-current-release-v1" || !Component.IsMatch(id) || !Digest.IsMatch(sha) ||
                Text(pointer, "app_root_relative") != "releases/" + id) throw Block("NATIVE_CURRENT_RELEASE_INVALID");
            string appRoot = Under(root, "releases/" + id);
            string manifestPath = Under(appRoot, "release-manifest.json");
            byte[] bytes = ReadBytes(manifestPath, 1024 * 1024);
            RequireHash(Hash(bytes), sha);
            var manifest = Document(bytes);
            if (Text(manifest, "schema_version") != "ops-release-manifest-v2" || Text(Map(manifest["identity"]), "release_id") != id ||
                Text(Map(manifest["enterprise_source"]), "repository") != "MEIS-DaCaiTou/Infinite-Canvas-Enterprise")
                throw Block("NATIVE_RELEASE_IDENTITY_INVALID");
            return new InstallIdentity { Root = root, AppRoot = appRoot, ReleaseId = id, ManifestSha = sha, Python = Under(appRoot, "python/python.exe") };
        }
        internal static void VerifyPayload(InstallIdentity install) {
            var manifest = ReadJson(Under(install.AppRoot, "release-manifest.json"), 1024 * 1024);
            var payload = Map(manifest["release_payload"]);
            string inventoryPath = Under(install.AppRoot, Text(payload, "inventory_path"));
            byte[] raw = ReadBytes(inventoryPath, 4 * 1024 * 1024);
            RequireHash(Hash(raw), Text(payload, "inventory_sha256"));
            var inventory = Document(raw);
            if (Text(inventory, "schema_version") != "ops-release-payload-inventory-v1") throw Block("NATIVE_INVENTORY_INVALID");
            object[] files = List(inventory, "entries");
            if (files.Length < 1 || files.Length > 20000) throw Block("NATIVE_INVENTORY_INVALID");
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object item in files) {
                var entry = Map(item);
                string path = Text(entry, "path");
                if (!seen.Add(path)) throw Block("NATIVE_INVENTORY_INVALID");
                string file = Under(install.AppRoot, path);
                if (new FileInfo(file).Length != Convert.ToInt64(entry["size_bytes"])) throw Block("NATIVE_FILE_SIZE_MISMATCH");
                RequireHash(HashFile(file), Text(entry, "sha256"));
            }
            if (!seen.Contains("python/python.exe") || !seen.Contains("enterprise/runtime/launcher.py"))
                throw Block("NATIVE_INVENTORY_INCOMPLETE");
            // Reject extra modules before Python import, not only changed files.
            seen.Add(Text(payload, "embedded_manifest_path")); seen.Add(Text(payload, "inventory_path"));
            var directories = new Stack<string>(); directories.Push(install.AppRoot);
            int visited = 0;
            while (directories.Count > 0) {
                string directory = directories.Pop(); SafePath(directory, false);
                foreach (string child in Directory.EnumerateFileSystemEntries(directory)) {
                    if (++visited > 40000) throw Block("NATIVE_INVENTORY_INVALID");
                    SafePath(child, false);
                    if (Directory.Exists(child)) directories.Push(child);
                    else {
                        string relative = child.Substring(install.AppRoot.Length + 1).Replace('\\', '/');
                        if (!seen.Remove(relative)) throw Block("NATIVE_INVENTORY_UNEXPECTED_FILE");
                    }
                }
            }
            if (seen.Count != 0) throw Block("NATIVE_INVENTORY_INCOMPLETE");
        }
        // Windows CreateProcess quoting, including quotes and trailing slashes.
        internal static string Quote(string argument) {
            var text = new StringBuilder("\"");
            int slashes = 0;
            foreach (char ch in argument) {
                if (ch == '\\') { slashes++; continue; }
                if (ch == '"') text.Append('\\', slashes * 2 + 1);
                else text.Append('\\', slashes);
                slashes = 0; text.Append(ch);
            }
            text.Append('\\', slashes * 2); text.Append('"');
            return text.ToString();
        }
        internal static Dictionary<string, object> RunPython(InstallIdentity install, string script, IEnumerable<string> arguments) {
            SafePath(script, false);
            var start = new ProcessStartInfo(install.Python, String.Join(" ", new[] { "-I", "-B", script }.Concat(arguments).Select(Quote))) {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = install.AppRoot,
                RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            foreach (string name in new[] { "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT" }) start.EnvironmentVariables.Remove(name);
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            using (var process = Process.Start(start)) {
                process.StandardInput.Close();
                // Drain both streams without storing raw errors or customer data.
                string last = null;
                var outputTask = Task.Run(() => {
                    string line;
                    while ((line = process.StandardOutput.ReadLine()) != null) {
                        if (line.Length <= 65536 && line.StartsWith("{", StringComparison.Ordinal)) last = line;
                    }
                });
                var errorTask = Task.Run(() => { while (process.StandardError.ReadLine() != null) { } });
                process.WaitForExit(); Task.WaitAll(outputTask, errorTask);
                if (last == null) throw Block("NATIVE_WORKER_RESULT_MISSING");
                var result = Map(Json.DeserializeObject(last));
                result["worker_exit_code"] = process.ExitCode;
                return result;
            }
        }
        internal static void WriteResult(string path, Dictionary<string, object> result) {
            if (path == null) return;
            SafePath(path, true);
            SafePath(Path.GetDirectoryName(Path.GetFullPath(path)), false);
            byte[] bytes = new UTF8Encoding(false).GetBytes(Json.Serialize(result) + "\n");
            using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                stream.Write(bytes, 0, bytes.Length); stream.Flush(true);
            }
        }
        internal static string BrowserUrl(Dictionary<string, object> result) {
            for (int i = 0; i < 4; i++) {
                object listener, status;
                if (result.TryGetValue("gateway_listener", out listener)) {
                    object port;
                    if (Map(listener).TryGetValue("port", out port)) {
                        int number = Convert.ToInt32(port);
                        if (number > 0 && number <= 65535) return "http://127.0.0.1:" + number + "/";
                    }
                }
                if (!result.TryGetValue("status", out status) || !(status is Dictionary<string, object>)) break;
                result = Map(status);
            }
            return null; // Never guess a configured port or follow a supplied URL.
        }
        internal static Dictionary<string, string> Options(string[] args, IEnumerable<string> switches, IEnumerable<string> values) {
            var flags = new HashSet<string>(switches); var named = new HashSet<string>(values);
            var result = new Dictionary<string, string>();
            for (int i = 0; i < args.Length; i++) {
                string key = args[i];
                if (result.ContainsKey(key)) throw Block("NATIVE_ARGUMENT_INVALID");
                if (flags.Contains(key)) result[key] = "1";
                else if (named.Contains(key) && i + 1 < args.Length) result[key] = args[++i];
                else throw Block("NATIVE_ARGUMENT_INVALID");
            }
            return result;
        }
    }

    // Read-only diagnostics remain available when neither Python nor the service starts.
    internal sealed class NativeDiagnostics {
        private static readonly Regex Identifier = new Regex(@"\A[0-9a-f]{32}\z");
        private static readonly Regex ValuePattern = new Regex(@"\A[A-Za-z0-9_.:+-]{1,160}\z");
        private static readonly Regex StartupPhase = new Regex(
            @"(?:^|\s)startup_phase instance=([0-9a-f]{32}) name=([a-z_]+) outcome=([a-z]+) elapsed_ms=([0-9.]+)");
        private static readonly Regex ReceiptCount = new Regex(@"""startup\.receipts_seen""\s*:\s*\{""calls""\s*:\s*(\d+)");
        private static readonly Regex FinishedReceiptCount = new Regex(@"""valid_receipts""\s*:\s*(\d+)");
        private static readonly Regex SetupCode = new Regex(@"\b(?:INSTALL|SYSTEM_UPDATE|RUNTIME|PORTABLE|NATIVE)_[A-Z0-9_]{2,80}\b");
        private static readonly string[] RuntimeKeys = ("schema_version release_id previous_release_id instance_id supervisor_instance_id " +
            "lock_phase owner_pid owner_process_created_at supervisor_pid supervisor_process_created_at state state_generation " +
            "pid process_created_at parent_pid health restart_count started_at updated_at created_at activated_at stop_phase").Split(' ');
        private static readonly string[] OperationKeys = ("result code worker_exit_code launcher_exit_code job_id operation_id " +
            "source_release_id target_release_id release_id command state recovery_required failure_code result_code failure_stage " +
            "startup_instance_id startup_state_settled upstream_last_startup_phase upstream_last_startup_outcome upstream_port_status " +
            "gateway_last_startup_phase gateway_last_startup_outcome gateway_port_status host_exit_code bootstrap_failure_category " +
            "recorded_at created_at updated_at").Split(' ');
        private static readonly string[] EventKeys = OperationKeys.Concat(("event phase role ts supervisor_instance_id " +
            "supervisor_pid pid parent_pid process_created_at health_category status_code elapsed_ms reason failure_category " +
            "startup_state_settled start_disposition lock_phase supervisor_current owned_child_current " +
            "upstream_pid upstream_process_created_at gateway_pid gateway_process_created_at").Split(' ')).ToArray();
        private static readonly string[] Phases = { "target_start", "target_health", "target_stop", "source_start", "source_health" };
        private readonly Dictionary<string, object> sources = new Dictionary<string, object>();
        private readonly Dictionary<string, object> evidence = new Dictionary<string, object>();

        private static Dictionary<string, object> Map(object value) {
            return value as Dictionary<string, object> ?? new Dictionary<string, object>();
        }

        private static object Value(Dictionary<string, object> fields, string key) {
            object value;
            return fields.TryGetValue(key, out value) ? value : null;
        }

        private static Dictionary<string, object> Select(Dictionary<string, object> fields, IEnumerable<string> keys) {
            var result = new Dictionary<string, object>();
            foreach (string key in keys) {
                object value = Value(fields, key);
                if (value is int || value is long || value is bool || value is double || value is decimal ||
                    (value is string && ValuePattern.IsMatch((string)value))) result[key] = value;
            }
            return result;
        }

        private static bool CollectionError(Exception error) {
            return error is IOException || error is UnauthorizedAccessException || error is InvalidOperationException ||
                   error is ArgumentException || error is System.Security.SecurityException;
        }

        private Dictionary<string, object> CollectJson(string root, string relative, string name) {
            try {
                var item = Core.ReadJson(Core.Under(root, relative), 128 * 1024);
                sources[name] = "collected";
                return item;
            } catch (Exception error) when (CollectionError(error) || error is FormatException) {
                sources[name] = Core.Code(error) == "NATIVE_PATH_MISSING" ? "missing" : "unavailable";
                return new Dictionary<string, object>();
            }
        }

        private void CollectLog(string path, string name, Func<string, object> project) {
            const int bytesLimit = 256 * 1024, recordLimit = 72;
            try {
                Core.SafePath(path, false);
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                                                   FileShare.ReadWrite | FileShare.Delete)) {
                    bool partial = stream.Length > bytesLimit;
                    stream.Seek(Math.Max(0, stream.Length - bytesLimit), SeekOrigin.Begin);
                    var bytes = new byte[bytesLimit];
                    int count = 0, read;
                    while (count < bytes.Length && (read = stream.Read(bytes, count, bytes.Length - count)) > 0) count += read;
                    var records = Encoding.UTF8.GetString(bytes, 0, count).Split('\n')
                        .Select(project).Where(item => item != null).Reverse().Take(recordLimit + 1).ToArray();
                    evidence[name] = records.Take(recordLimit).Reverse().ToArray();
                    sources[name] = partial || records.Length > recordLimit ? "tail" : "collected";
                }
            } catch (Exception error) when (CollectionError(error)) {
                sources[name] = Core.Code(error) == "NATIVE_PATH_MISSING" ? "missing" : "unavailable";
            }
        }

        private static object LogEvent(string line) {
            if (line.Length > 4096 || !line.StartsWith("{", StringComparison.Ordinal)) return null;
            try {
                var item = Map(Core.Json.DeserializeObject(line));
                if (!item.ContainsKey("event") && !item.ContainsKey("ts")) return null;
                var entry = Select(item, EventKeys);
                var observation = Map(Value(item, "startup_observation"));
                if (observation.Count != 0) entry["startup_observation"] = Select(observation, EventKeys.Concat(RuntimeKeys));
                return entry;
            } catch (Exception error) when (CollectionError(error)) { return null; }
        }

        private static object StartupEvent(string line) {
            var phase = StartupPhase.Match(line);
            if (phase.Success) {
                var finished = FinishedReceiptCount.Match(line);
                return new {
                    instance_id = phase.Groups[1].Value, phase = phase.Groups[2].Value,
                    outcome = phase.Groups[3].Value, elapsed_ms = phase.Groups[4].Value,
                    valid_receipts = finished.Success ? finished.Groups[1].Value : null
                };
            }
            var count = ReceiptCount.Match(line);
            return count.Success ? (object)new { receipts_seen = count.Groups[1].Value } : null;
        }

        private static object SetupEvent(string line) {
            // Setup's free-form log can contain command lines and user paths.
            // Retain only our stable codes from bounded log records.
            var match = SetupCode.Match(line);
            if (!match.Success) return null;
            var time = Regex.Match(line, @"\A\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)");
            return new { ts = time.Success ? time.Groups[1].Value : null, code = match.Value };
        }

        private static object ObserveProcess(object pidValue) {
            int pid;
            if (pidValue == null || !Int32.TryParse(pidValue.ToString(), out pid) || pid <= 0) return null;
            try {
                using (var process = Process.GetProcessById(pid)) {
                    string executable = null;
                    try { executable = Path.GetFileName(process.MainModule.FileName); }
                    catch (System.ComponentModel.Win32Exception) { }
                    return new { pid, observed = "running", created_at = process.StartTime.ToUniversalTime().ToFileTimeUtc(), executable };
                }
            } catch (ArgumentException) { return new { pid, observed = "absent" }; }
              catch (Exception error) when (CollectionError(error) || error is System.ComponentModel.Win32Exception) {
                return new { pid, observed = "unavailable" };
            }
        }

        private void CollectListeners(string root) {
            try {
                var ports = new Dictionary<string, int> { { "UPSTREAM_PORT", 3001 }, { "GATEWAY_PORT", 8000 } };
                string path = Core.Under(root, "config/enterprise.env");
                foreach (Match item in Regex.Matches(Encoding.UTF8.GetString(Core.ReadBytes(path, 128 * 1024)),
                    @"(?m)^\s*(UPSTREAM_PORT|GATEWAY_PORT)\s*=\s*(\d{1,5})\s*(?:#.*)?$")) {
                    int port;
                    if (Int32.TryParse(item.Groups[2].Value, out port) && port > 0 && port <= 65535) ports[item.Groups[1].Value] = port;
                }
                var listeners = IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners();
                evidence["listeners"] = ports.Select(pair => new {
                    name = pair.Key, port = pair.Value, listening = listeners.Any(endpoint => endpoint.Port == pair.Value)
                }).ToArray();
                sources["listeners"] = "collected";
            } catch (Exception error) when (CollectionError(error) || error is System.ComponentModel.Win32Exception) {
                sources["listeners"] = "unavailable";
            }
        }

        private void CollectJobs(string root, string activeJob) {
            var selected = new List<string>();
            if (activeJob != null && Identifier.IsMatch(activeJob)) selected.Add(activeJob);
            try {
                var directory = new DirectoryInfo(Core.Under(root, "staging/update-mvp/jobs"));
                selected.AddRange(directory.EnumerateDirectories().Where(item => Identifier.IsMatch(item.Name))
                    .OrderByDescending(item => item.LastWriteTimeUtc).Take(3).Select(item => item.Name));
                sources["update_jobs"] = "collected";
            } catch (Exception error) when (CollectionError(error)) {
                sources["update_jobs"] = Core.Code(error) == "NATIVE_PATH_MISSING" ? "missing" : "unavailable";
            }
            foreach (var id in selected.Distinct()) {
                string relative = "staging/update-mvp/jobs/" + id + "/";
                var item = CollectJson(root, relative + "status.json", "job/" + id);
                var status = Select(item, OperationKeys);
                var phases = Map(Value(item, "runtime_phases"));
                foreach (var phase in Phases)
                    if (phases.ContainsKey(phase)) status[phase] = Select(Map(phases[phase]), OperationKeys);
                evidence["job/" + id] = status;
                CollectLog(Path.Combine(root, relative + "events.jsonl"), "job_events/" + id, LogEvent);
            }
        }

        private void Collect(string root, string setupLog) {
            var pointer = CollectJson(root, "state/current-release.json", "release");
            evidence["release"] = Select(pointer, RuntimeKeys);
            var active = CollectJson(root, "state/install-upgrade-active.json", "upgrade");
            var operation = Value(active, "operation_id") as string;
            string job = null;
            if (operation != null && Identifier.IsMatch(operation)) {
                string relative = "state/install-upgrades/" + operation + "/";
                var state = CollectJson(root, relative + "state.json", "upgrade_state");
                evidence["upgrade_state"] = Select(state, OperationKeys);
                job = Value(state, "job_id") as string;
            }
            CollectJobs(root, job);
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!String.IsNullOrEmpty(local)) {
                const string runtime = "InfiniteCanvasEnterprise/runtime/";
                evidence["launch_context"] = Select(CollectJson(local, runtime + "launch-context.json", "launch_context"), RuntimeKeys);
                var state = CollectJson(local, runtime + "runtime-state.json", "runtime_state");
                var runtimeLock = CollectJson(local, runtime + "runtime-supervisor.lock", "runtime_lock");
                var runtimeState = Select(state, RuntimeKeys);
                var processes = new Dictionary<string, object> {
                    { "supervisor", ObserveProcess(Value(state, "supervisor_pid")) },
                    { "owner", ObserveProcess(Value(runtimeLock, "owner_pid")) }
                };
                foreach (string role in new[] { "upstream", "gateway" }) {
                    var record = Map(Value(state, role));
                    runtimeState[role] = Select(record, RuntimeKeys);
                    processes[role] = ObserveProcess(Value(record, "pid"));
                }
                evidence["runtime_state"] = runtimeState;
                evidence["runtime_lock"] = Select(runtimeLock, RuntimeKeys);
                evidence["processes"] = processes;
            } else sources["runtime_state"] = "unavailable";
            CollectListeners(root);
            foreach (string name in new[] { "launcher.log", "launcher.log.1", "supervisor.log", "health.log", "crash-events.jsonl" })
                CollectLog(Path.Combine(root, "logs/runtime", name), name, LogEvent);
            foreach (string name in new[] { "upstream.stderr.log", "gateway.stderr.log" })
                CollectLog(Path.Combine(root, "logs/runtime", name), name, StartupEvent);
            if (!String.IsNullOrEmpty(setupLog)) CollectLog(setupLog, "setup_log", SetupEvent);
        }

        internal static void Export(string path, string root, Dictionary<string, object> result, string setupLog = null) {
            var report = new NativeDiagnostics();
            report.Collect(root, setupLog);
            var document = new Dictionary<string, object> {
                { "schema_version", "enterprise-native-diagnostics-v2" },
                { "generated_at", DateTime.UtcNow.ToString("o") }, { "operation", Select(result, OperationKeys) },
                { "sources", report.sources }, { "evidence", report.evidence }
            };
            var bytes = Encoding.UTF8.GetBytes(Core.Json.Serialize(document) + "\n");
            Core.SafePath(path, true);
            string parent = Path.GetDirectoryName(path);
            Core.SafePath(parent, false);
            string temporary = Path.Combine(parent, ".canvas-diagnostic-" + Guid.NewGuid().ToString("N") + ".tmp");
            try {
                using (var target = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                    using (var zip = new ZipArchive(target, ZipArchiveMode.Create, true))
                    using (var entry = zip.CreateEntry("native-diagnostics.json").Open()) entry.Write(bytes, 0, bytes.Length);
                    target.Flush(true);
                }
                File.Move(temporary, path);
            } finally { File.Delete(temporary); }
        }
    }
}
