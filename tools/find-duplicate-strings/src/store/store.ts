import type { Finding } from "../typings/finding.js";

let findings: Map<string, Finding> = new Map();

export const store = {
  add(key: string, value: Finding): void {
    if (findings.has(key)) {
      throw new Error(`Key ${key} already exists`);
    }

    findings.set(key, value);
  },
  find(key: string): Finding | null {
    return findings.get(key) || null;
  },
  getAll(): Finding[] {
    return Array.from(findings.values());
  },
  clear() {
    findings = new Map();
  },
};
