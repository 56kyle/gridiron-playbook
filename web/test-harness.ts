import * as storage from "./src/storage";
import * as gameFiles from "./src/gameFiles";
import * as engine from "./src/engine";

declare global {
  interface Window {
    testStorage: typeof storage;
    testGameFiles: typeof gameFiles;
    testEngine: typeof engine;
  }
}

window.testStorage = storage;
window.testGameFiles = gameFiles;
window.testEngine = engine;
document.getElementById("status")!.textContent = "Ready";
