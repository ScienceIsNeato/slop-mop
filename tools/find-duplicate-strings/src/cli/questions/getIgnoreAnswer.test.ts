import { equal } from "node:assert";
import { mock, suite, test } from "node:test";

const mockInput = mock.fn(() => "dummy");
mock.module("@inquirer/prompts", {
	namedExports: {
		input: mockInput,
	},
});

const { getIgnoreAnswer } = await import("./getIgnoreAnswer.js");

suite("getIgnoreAnswer", () => {
	test("should return the answer when it is found", async () => {
		const answer = await getIgnoreAnswer();

		equal(answer, "dummy");
	});
});
