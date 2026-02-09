import { input } from '@inquirer/prompts';

export function getIgnoreAnswer(): Promise<string> {
  return input({
    message:
      'Please provide a comma separated list of glob patterns for directories/files to ignore (optional)',
  });
}
