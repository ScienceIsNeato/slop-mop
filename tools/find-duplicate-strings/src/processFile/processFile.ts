import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';

import { store } from '../store/store.js';

export function processFile(path: string): Promise<void> {
  const isPython = path.endsWith('.py');

  return new Promise((resolve) => {
    let inMultiLineDocstring = false;
    let docstringDelimiter = '';

    createInterface({
      input: createReadStream(path, { encoding: 'utf-8' }),
      terminal: false,
    })
      .on('line', (line) => {
        let processedLine = line;

        if (isPython) {
          // Track multi-line triple-quoted docstrings
          if (inMultiLineDocstring) {
            if (line.includes(docstringDelimiter)) {
              inMultiLineDocstring = false;
              docstringDelimiter = '';
            }
            return; // Skip lines inside multi-line docstrings
          }

          // Strip single-line triple-quoted strings: """...""" or '''...'''
          processedLine = processedLine.replace(/"{3}[^"]*"{3}/g, '');
          processedLine = processedLine.replace(/'{3}[^']*'{3}/g, '');

          // Detect start of multi-line triple-quoted docstrings
          // (opening triple-quote without a matching close on the same line)
          if (/"{3}/.test(processedLine)) {
            inMultiLineDocstring = true;
            docstringDelimiter = '"""';
            return;
          }
          if (/'{3}/.test(processedLine)) {
            inMultiLineDocstring = true;
            docstringDelimiter = "'''";
            return;
          }
        }

        const matches = processedLine.match(/(?:("[^"\\]*(?:\\.[^"\\]*)*")|('[^'\\]*(?:\\.[^'\\]*)*'))/g);

        if (matches) {
          for (const match of matches) {
            const isNotEmpty = match && match.length > 2;
            if (isNotEmpty) {
              storeMatch(match.substring(1, match.length - 1), path);
            }
          }
        }
      })
      .on('close', () => {
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
