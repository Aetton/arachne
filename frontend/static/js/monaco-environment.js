  window.MonacoEnvironment = {
    getWorkerUrl: function () {
      var source = "self.MonacoEnvironment={baseUrl:'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/'};" +
        "importScripts('https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/base/worker/workerMain.js');";
      return URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
    }
  };
