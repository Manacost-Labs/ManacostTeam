// Compatibility entrypoint; the canonical helper ships with the Python package.
const bank = require('../src/editorteam/example_bank.js');
if (require.main === module) {
  try { bank.main(process.argv.slice(2)); } catch (error) { console.error(`error: ${error.message}`); process.exitCode = 2; }
}
module.exports = bank;
