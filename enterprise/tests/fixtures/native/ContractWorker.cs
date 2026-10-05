// Test-only process handoff. Never shipped or used as a Python interpreter.
using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;
internal static class ContractWorker {
    private static int Main(string[] args) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        var result = new Dictionary<string, object> {
            { "result", "fixture-only-no-service" },
            { "argv", args }, { "cwd", Environment.CurrentDirectory },
            { "pythonpath_removed", Environment.GetEnvironmentVariable("PYTHONPATH") == null },
            { "pythonhome_removed", Environment.GetEnvironmentVariable("PYTHONHOME") == null },
            { "no_user_site", Environment.GetEnvironmentVariable("PYTHONNOUSERSITE") },
            { "no_bytecode", Environment.GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE") }
        };
        Console.WriteLine(new JavaScriptSerializer().Serialize(result));
        return 0;
    }
}
