import { getIgnoreAnswer } from "../cli/questions/getIgnoreAnswer.js";
import { getThresholdAnswer } from "../cli/questions/getThresholdAnswer.js";
import { getFiles } from "../getFiles/getFiles.js";
import { getPathsToIgnore } from "../getPathsToIgnore/getPathsToIgnore.js";
import { Loader } from "../loader/loader.js";
import { Output } from "../output/output.js";
import { processFile } from "../processFile/processFile.js";
import { store } from "../store/store.js";

import type { Finding } from "../typings/finding.js";

interface Options {
  ignore?: string;
  output?: string;
  interactive?: boolean;
  json?: boolean;
  path: string;
  threshold?: string;
}

export class Scanner {
  private ignore!: string[];
  private threshold!: number;
  private output!: string;
  private interactive!: boolean;
  private json!: boolean;
  private path: string;

  public constructor(
    private options: Options,
    private loaderInterval = 1000,
  ) {
    this.ignore = getPathsToIgnore(options.ignore);
    this.threshold =
      typeof options.threshold === "string"
        ? Number.parseInt(options.threshold, 10)
        : 1;
    this.output = options.output ?? "fds-output";
    this.interactive = options.interactive ?? false;
    this.json = options.json ?? false;
    this.path = options.path;
  }

  public async scan(): Promise<void> {
    if (!this.options.ignore && this.interactive) {
      const answer = await getIgnoreAnswer();
      this.ignore = getPathsToIgnore(answer);
    }

    if (!this.options.threshold && this.interactive) {
      const answer = await getThresholdAnswer();
      this.threshold = Number.parseInt(answer, 10);
    }

    await this.initScan();

    const duplicates = this.getDuplicates();

    if (!duplicates.length) {
      if (this.json) {
        console.log(JSON.stringify([]));
      } else {
        console.log("No duplicates where found.");
      }
      return;
    }

    if (this.json) {
      // Output JSON to stdout for programmatic use
      console.log(JSON.stringify(duplicates, null, 2));
    } else {
      new Output(duplicates, this.output).output();
    }
  }

  private async scanDir() {
    const files = getFiles(this.path, this.ignore);
    const openFilesLimit = 1024;
    const shard = Math.ceil(files.length / openFilesLimit);

    for (let i = 0; i < shard; i++) {
      await Promise.all(files.splice(i, openFilesLimit).map(this.scanFile));
    }
  }

  private scanFile(path: string): Promise<void> {
    return processFile(path);
  }

  private getDuplicates(): Finding[] {
    return store.getAll().filter((value) => value.count > this.threshold);
  }

  private async initScan() {
    const loader = new Loader(this.loaderInterval);
    await this.scanDir();
    loader.destroy();
  }
}
