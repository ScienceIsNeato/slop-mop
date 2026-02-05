import { deepEqual } from "node:assert";
import { dirname, resolve } from "node:path";
import { beforeEach, suite, test } from "node:test";
import { fileURLToPath } from "node:url";

import { store } from "../store/store.js";
import { processFile } from "./processFile.js";

suite("processFile", () => {
	beforeEach(() => {
		store.clear();
	});

	test("should add and update matches to store", async () => {
		const path1 = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/file1.js",
		);
		const path2 = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/file2.js",
		);

		await processFile(path1);

		deepEqual(store.getAll(), [
			{
				key: "foo",
				count: 1,
				fileCount: 1,
				files: [path1],
			},
			{
				key: "bar",
				count: 1,
				fileCount: 1,
				files: [path1],
			},
		]);

		await processFile(path2);

		deepEqual(store.getAll(), [
			{
				key: "foo",
				count: 4,
				fileCount: 2,
				files: [path1, path2],
			},
			{
				key: "bar",
				count: 1,
				fileCount: 1,
				files: [path1],
			},
		]);
	});

	test("should not store empty string values", async () => {
		const path = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/empty-strings-file.js",
		);

		await processFile(path);

		deepEqual(store.getAll(), []);
	});

	test("should not store the same path path twice", async () => {
		const path = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/file2.js",
		);

		await processFile(path);

		deepEqual(store.getAll(), [
			{
				key: "foo",
				count: 3,
				fileCount: 1,
				files: [path],
			},
		]);
	});

	test("should store all matches", async () => {
		const path = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/file3.js",
		);

		await processFile(path);

		deepEqual(store.getAll(), [
			{
				key: "foo",
				count: 2,
				fileCount: 1,
				files: [path],
			},
			{
				key: "f'o''o'bar",
				count: 1,
				fileCount: 1,
				files: [path],
			},
			{
				key: "bar",
				count: 1,
				fileCount: 1,
				files: [path],
			},
		]);
	});

	test("should not call the store when there are no strings/matches", async () => {
		const path = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/no-strings-file",
		);

		await processFile(path);

		deepEqual(store.getAll(), []);
	});

	test("should not call the store when the file is empty", async () => {
		const path = resolve(
			dirname(fileURLToPath(import.meta.url)),
			"./mocks/empty-file",
		);

		await processFile(path);

		deepEqual(store.getAll(), []);
	});
});
