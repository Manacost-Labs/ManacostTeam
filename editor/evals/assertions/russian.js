// Narrow lexical contracts for named regression cases, never a global style score.
module.exports = function russian(output, context = {}) {
  const contract = context.vars?.russian_contract;
  if (!contract || !Array.isArray(contract.required) || !Array.isArray(contract.forbidden)
    || contract.required.some((group) => !Array.isArray(group) || !group.length || group.some((phrase) => typeof phrase !== 'string' || !phrase.trim()))
    || contract.forbidden.some((phrase) => typeof phrase !== 'string' || !phrase.trim())) throw new Error('valid russian_contract required');
  const normalized = (text) => String(text).normalize('NFKC').toLocaleLowerCase('ru').replace(/\s+/gu, ' ').trim();
  const text = normalized(output);
  const missing = contract.required.filter((group) => !group.some((phrase) => text.includes(normalized(phrase))));
  const forbidden = contract.forbidden.filter((phrase) => text.includes(normalized(phrase)));
  const pass = Boolean(text) && !missing.length && !forbidden.length;
  return { pass, score: pass ? 1 : 0, reason: pass ? 'russian regression contract: ok' : `missing groups: ${JSON.stringify(missing)}; forbidden: ${JSON.stringify(forbidden)}` };
};
