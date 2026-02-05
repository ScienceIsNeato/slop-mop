export function getPathsToIgnore(ignoreList?: string): string[] {
	return (
		ignoreList
			?.split?.(",")
			.map((path) => path.trim())
			.filter((path) => path) || []
	);
}
