import { deepEqual } from "node:assert";
import { beforeEach, mock, suite, test } from "node:test";

const mockGlobSync = mock.fn((): string[] => []);
const mockExistsSync = mock.fn(() => true);

mock.module("glob", {
  namedExports: {
    globSync: mockGlobSync,
  },
});
mock.module("node:fs", {
  namedExports: {
    existsSync: mockExistsSync,
  },
});

const { getFiles } = await import("./getFiles.js");

suite("getFiles", () => {
  beforeEach(() => {
    mockGlobSync.mock.resetCalls();
    mockExistsSync.mock.resetCalls();
  });

  test("should return files", async () => {
    mockGlobSync.mock.mockImplementation(() => ["file1", "file2"]);
    const files = getFiles("dummy-directory", []);

    deepEqual(files, ["file1", "file2"]);
  });

  test("should ignore files from directory: node_modules and coverage", () => {
    getFiles("dummy-directory", ["node_modules", "coverage"]);

    deepEqual(mockGlobSync.mock.calls.at(0)?.arguments, [
      "dummy-directory",
      {
        absolute: true,
        ignore: ["node_modules", "coverage"],
        matchBase: true,
        nodir: true,
        realpath: true,
      },
    ]);
  });
});
