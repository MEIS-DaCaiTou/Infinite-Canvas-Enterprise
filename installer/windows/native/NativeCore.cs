// Thin Windows presentation/bootstrap layer. Lifecycle and DATA remain Python.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace InfiniteCanvas.Native {
    internal sealed class InstallIdentity {
        internal string Root, AppRoot, ReleaseId, ManifestSha, Python;
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
        internal static void ExportReport(string path, Dictionary<string, object> result) {
            string[] keys = { "result", "code", "job_id", "source_release_id", "target_release_id", "source_version", "release_id",
                "manifest_sha256", "source_manifest_sha256", "database_variant", "database_objects_sha256", "object_count",
                "integrity_check", "terminal_state", "result_code", "source_recovery", "launcher_installed", "launcher_code", "worker_exit_code" };
            var summary = new Dictionary<string, object>();
            foreach (string key in keys) {
                object value;
                if (result.TryGetValue(key, out value) && (value is string || value is bool || value is int)) summary[key] = value;
            }
            var document = new Dictionary<string, object> { { "schema_version", "enterprise-native-diagnostics-v1" },
                { "generated_at", DateTime.UtcNow.ToString("o") }, { "operation", summary } };
            byte[] bytes = Encoding.UTF8.GetBytes(Json.Serialize(document) + "\n");
            SafePath(path, true); SafePath(Path.GetDirectoryName(path), false);
            using (var target = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            using (var zip = new ZipArchive(target, ZipArchiveMode.Create))
            using (var entry = zip.CreateEntry("native-diagnostics.json").Open()) entry.Write(bytes, 0, bytes.Length);
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
}
