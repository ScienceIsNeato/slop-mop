import { createWriteStream, existsSync } from "node:fs";
import { resolve } from "node:path";

import type { Finding } from "../typings/finding.js";

export class Output {
  private data: Finding[];
  private path: string;
  private count = 0;

  public constructor(
    input: Finding[],
    private outputFileName = "fds-output",
  ) {
    this.data = input.sort((a, b) => b.count - a.count);
    this.path = resolve(process.cwd(), `${this.outputFileName}.json`);
  }

  public output(): void {
    const createFileName = (path: string) => {
      if (existsSync(path)) {
        return createFileName(
          resolve(process.cwd(), `${this.outputFileName}-${++this.count}.json`),
        );
      }
      return path;
    };

    this.outputToFile(this.data, createFileName(this.path));
  }

  private outputToFile(output: Finding[], filePath: string): void {
    const writeStream = createWriteStream(filePath, {
      flags: "w",
    });
    writeStream.write("[");
    output.forEach((finding, i) => {
      writeStream.write(JSON.stringify(finding, null, 2));
      if (i !== output.length - 1) {
        writeStream.write(",");
      }
    });
    writeStream.write("]");
  }
}
