import type { Finding } from "../../typings/finding.js";

export const findings: Finding[] = [
	{
		key: "foo",
		count: 1,
		fileCount: 1,
		files: ["dummy/path/1"],
	},
	{
		key: "foo",
		count: 2,
		fileCount: 1,
		files: ["dummy/path/2"],
	},
];

export const manyFindings = (count: number) =>
	Array.from({ length: count }).map((_, i) => ({
		key: "foo",
		count: i + 1,
		fileCount: 1,
		files: [`dummy/path/${i + 1}`],
	}));
