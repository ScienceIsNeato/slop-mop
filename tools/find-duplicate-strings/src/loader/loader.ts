export class Loader {
	private loaderTimer: NodeJS.Timeout;
	private count = 0;

	constructor(loaderInterval: number) {
		process.on("SIGTERM", () => {
			this.destroy();
		});
		process.on("SIGINT", () => {
			this.destroy();
		});

		this.loaderTimer = setInterval(() => {
			this.count++;
			if (this.count > 10) {
				this.count = 0;
				this.clearLine();
				return;
			}

			// Only write progress dots in TTY mode
			if (process.stdout.isTTY) {
				process.stdout.write(".");
			}
		}, loaderInterval);
	}

	destroy = () => {
		clearInterval(this.loaderTimer);
		process.removeAllListeners("SIGTERM");
		process.removeAllListeners("SIGINT");
		this.clearLine();
	};

	private clearLine() {
		// Guard for non-TTY environments (e.g., piped output, subprocess)
		if (process.stdout.clearLine) {
			process.stdout.clearLine(0);
		}
		if (process.stdout.cursorTo) {
			process.stdout.cursorTo(0);
		}
	}
}
