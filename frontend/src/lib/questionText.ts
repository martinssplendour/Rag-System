export function normalisePastedQuestionText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/([A-Za-z])%([A-Za-z])/g, "$1ti$2");
}
