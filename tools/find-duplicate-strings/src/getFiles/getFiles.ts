import { globSync } from "glob";

export function getFiles(path: string, ignore: string[]): string[] {
	return globSync(path, {
		nodir: true,
		realpath: true,
		absolute: true,
		matchBase: true,
		ignore,
	});
}
