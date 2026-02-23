const isTTY = process.stdout.isTTY ?? false;
let forceJson = false;
let noColor = false;

export function setForceJson(value: boolean) {
  forceJson = value;
}

export function setNoColor(value: boolean) {
  noColor = value;
}

export function isJsonMode(): boolean {
  return forceJson || !isTTY;
}

const ansi = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  cyan: "\x1b[36m",
};

function color(code: string, text: string): string {
  if (noColor || !isTTY) return text;
  return `${code}${text}${ansi.reset}`;
}

export const fmt = {
  bold: (text: string) => color(ansi.bold, text),
  dim: (text: string) => color(ansi.dim, text),
  red: (text: string) => color(ansi.red, text),
  green: (text: string) => color(ansi.green, text),
  yellow: (text: string) => color(ansi.yellow, text),
  blue: (text: string) => color(ansi.blue, text),
  cyan: (text: string) => color(ansi.cyan, text),
  success: (text: string) => color(ansi.green, `✓ ${text}`),
  error: (text: string) => color(ansi.red, `✗ ${text}`),
  warn: (text: string) => color(ansi.yellow, `⚠ ${text}`),
};

export function outputResult(data: unknown, humanReadable: () => void): void {
  if (isJsonMode()) {
    console.log(JSON.stringify(data, null, 2));
  } else {
    humanReadable();
  }
}

export function outputError(message: string, details?: string): never {
  if (isJsonMode()) {
    console.error(JSON.stringify({ error: message, details }));
  } else {
    console.error(fmt.error(message));
    if (details) console.error(fmt.dim(details));
  }
  process.exit(1);
}

export async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk: string) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}
