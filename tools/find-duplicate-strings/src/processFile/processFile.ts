import { createReadStream } from "node:fs";
import { createInterface } from "node:readline";

import { store } from "../store/store.js";

export function processFile(path: string): Promise<void> {
  return new Promise((resolve) => {
    createInterface({
      input: createReadStream(path, { encoding: "utf-8" }),
      terminal: false,
    })
      .on("line", (line) => {
        const matches = line.match(
          /(?:("[^"\\]*(?:\\.[^"\\]*)*")|('[^'\\]*(?:\\.[^'\\]*)*'))/g,
        );

        if (matches) {
          for (const match of matches) {
            const isNotEmpty = match && match.length > 2;
            if (isNotEmpty) {
              storeMatch(match.substring(1, match.length - 1), path);
            }
          }
        }
      })
      .on("close", () => {
        resolve();
      });
  });
}

function storeMatch(key: string, path: string): void {
  const value = store.find(key);

  if (!value) {
    store.add(key, { key, count: 1, fileCount: 1, files: [path] });
    return;
  }

  if (!value.files.includes(path)) {
    value.files.push(path);
    value.fileCount++;
  }
  value.count++;
}
