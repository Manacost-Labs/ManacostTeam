const fs = require('node:fs');

module.exports = function load() {
  const path = process.env.EDITOR_EVAL_PUBLICATION_CASES;
  if (!path) throw new Error('EDITOR_EVAL_PUBLICATION_CASES is required; private articles are never bundled');
  const cases = JSON.parse(fs.readFileSync(path, 'utf8'));
  if (!Array.isArray(cases) || !cases.length) throw new Error('Nonempty approved case array required');
  const ids = new Set();
  return cases.map((item) => {
    if (!item.id || ids.has(item.id) || item.review_status !== 'approved' || !item.source || !item.reference || !item.research_handoff || !['train', 'holdout'].includes(item.split)) {
      throw new Error('Unique human-approved cases with source, reference, handoff and split required');
    }
    ids.add(item.id);
    return { description: `publication ${item.id}`, vars: {
      id: item.id, text: item.source, reference: item.reference,
      profile: item.research_handoff.style_profile, current_patch: item.research_handoff.patch,
      research_handoff: item.research_handoff, split: item.split,
    }};
  });
};
