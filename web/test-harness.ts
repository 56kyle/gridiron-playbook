import * as storage from "./src/storage";
import * as gameFiles from "./src/gameFiles";
import * as engine from "./src/engine";
import * as gameDirectory from "./src/gameDirectory";

declare global {
  interface Window {
    testStorage: typeof storage;
    testGameFiles: typeof gameFiles;
    testEngine: typeof engine;
    testGameDirectory: typeof gameDirectory;
  }
}

window.testStorage = storage;
window.testGameFiles = gameFiles;
window.testEngine = engine;
window.testGameDirectory = gameDirectory;
document.getElementById("status")!.textContent = "Ready";
