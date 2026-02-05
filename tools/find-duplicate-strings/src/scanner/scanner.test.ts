import { deepEqual, equal } from "node:assert";
import { beforeEach, mock, suite, test } from "node:test";

const mockGetIgnoreQuestionAnswer = mock.fn(() => Promise.resolve("dummy-dir"));
const mockGetThresholdAnswer = mock.fn(() => Promise.resolve("1"));
const mockProcessFile = mock.fn();
const mockOutput = mock.fn();
const mockGetFiles = mock.fn((): string[] => []);
const mockGetAll = mock.fn(() => [{ count: 1, files: [], key: "" }]);
const mockConsoleLog = mock.fn();

mock.module("../getFiles/getFiles.js", {
	namedExports: {
		getFiles: mockGetFiles,
	},
});
mock.module("../store/store.js", {
	namedExports: {
		store: { getAll: mockGetAll },
	},
});
mock.module("../cli/questions/getIgnoreAnswer.js", {
	namedExports: {
		getIgnoreAnswer: mockGetIgnoreQuestionAnswer,
	},
});
mock.module("../cli/questions/getThresholdAnswer.js", {
	namedExports: {
		getThresholdAnswer: mockGetThresholdAnswer,
	},
});
mock.module("../processFile/processFile.js", {
	namedExports: {
		processFile: mockProcessFile,
	},
});
mock.module("../output/output.js", {
	namedExports: {
		Output: class {
			output = mockOutput;
		},
	},
});

const { Scanner } = await import("./scanner.js");

console.log = mockConsoleLog;
process.stdout.clearLine = mock.fn();
process.stdout.cursorTo = mock.fn();
process.stdout.write = mock.fn();

const interval = 1;

mock.timers.enable({ apis: ["setInterval"] });

suite("Scanner", () => {
	beforeEach(() => {
		process.exit = mock.fn(() => undefined as never);
		mockGetIgnoreQuestionAnswer.mock.resetCalls();
		mockGetThresholdAnswer.mock.resetCalls();
		mockConsoleLog.mock.resetCalls();
		mockGetFiles.mock.resetCalls();
		mockProcessFile.mock.resetCalls();
		mockOutput.mock.resetCalls();
	});

	test("should enable interactive mode", async () => {
		const scanner = new Scanner({ interactive: true, path: "." }, interval);

		equal(scanner["interactive"], true);
	});

	test("should disable interactive mode", async () => {
		const scanner = new Scanner({ interactive: false, path: "." }, interval);

		equal(scanner["interactive"], false);
	});

	test("should set ignore", async () => {
		const scanner = new Scanner(
			{ ignore: "one,two,three", path: "." },
			interval,
		);

		deepEqual(scanner["ignore"], ["one", "two", "three"]);
	});

	test("should ask a question when ignore is not provided while interactive mode is enabled and the path does not point to a file", async () => {
		const scanner = new Scanner({ interactive: true, path: "." }, interval);

		await scanner.scan();

		equal(mockGetIgnoreQuestionAnswer.mock.callCount(), 1);
	});

	test("should not ask a question when ignore is not provided while interactive mode is disabled and the path does not point to a file", async () => {
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockGetIgnoreQuestionAnswer.mock.callCount(), 0);
	});

	test("should set a threshold when passing threshold as a string", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 5, files: [], key: "" },
		]);
		const scanner = new Scanner({ threshold: "3.55", path: "." }, interval);

		await scanner.scan();

		equal(scanner["threshold"], 3);
	});

	test("should ask a question when the threshold is not provided and interactive mode is enabled", async () => {
		const scanner = new Scanner({ interactive: true, path: "." }, interval);

		await scanner.scan();

		equal(mockGetThresholdAnswer.mock.callCount(), 1);
	});

	test("should not ask a question when the threshold is not provided and interactive mode is disabled", async () => {
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockGetThresholdAnswer.mock.callCount(), 0);
	});

	test("should scan all files found in the directory", async () => {
		mockGetFiles.mock.mockImplementation(() => ["", "", "", ""]);
		const scanner = new Scanner({ path: "" }, interval);

		await scanner.scan();

		equal(mockProcessFile.mock.callCount(), 4);
	});

	test("should scan the single file that is passed", async () => {
		mockGetFiles.mock.mockImplementation(() => [""]);
		const scanner = new Scanner({ path: "" }, interval);

		await scanner.scan();

		equal(mockProcessFile.mock.callCount(), 1);
	});

	test("should log a message to the console when no results are found", async () => {
		mockGetAll.mock.mockImplementation(() => []);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();
		equal(
			mockConsoleLog.mock.calls.at(0)?.arguments,
			"No duplicates where found.",
		);
	});

	test("should not trigger an output when no results are found", async () => {
		mockGetAll.mock.mockImplementation(() => []);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockOutput.mock.callCount(), 0);
	});

	test("should log a message to the console when results are found but the counts are lower then the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 0, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(
			mockConsoleLog.mock.calls.at(0)?.arguments,
			"No duplicates where found.",
		);
	});

	test("should not trigger an output when results are found but the counts are lower then the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 0, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockOutput.mock.callCount(), 0);
	});

	test("should log a message to the console when results are found but the counts are equal to the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 1, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(
			mockConsoleLog.mock.calls.at(0)?.arguments,
			"No duplicates where found.",
		);
	});

	test("should not trigger an output when results are found but the counts are equal to the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 1, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockOutput.mock.callCount(), 0);
	});

	test("should not log a message to the console when duplicates are found and the counts are higher then the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 2, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockConsoleLog.mock.callCount(), 0);
	});

	test("should trigger an output when duplicates are found and the counts are higher then the threshold", async () => {
		mockGetAll.mock.mockImplementation(() => [
			{ count: 2, files: [], key: "" },
		]);
		const scanner = new Scanner({ path: "." }, interval);

		await scanner.scan();

		equal(mockOutput.mock.callCount(), 1);
	});
});
