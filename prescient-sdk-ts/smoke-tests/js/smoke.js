// Point at the prescient-sdk-ts dist directly so Node.js resolves all deps
// through the project's pnpm node_modules. This is the correct approach for
// local testing because the tgz bundles direct deps but NOT their transitive
// deps (pnpm isolates those in .pnpm/). Real consumers install via npm/pip
// which resolves the full dep tree from the registry.
const { PrescientClient } = require('../../prescient-sdk-ts/dist/index');

const client = new PrescientClient({ envFile: '/workspace/smoke-tests/config.env' });

console.log('endpointUrl    :', client.settings.endpointUrl);
console.log('stacCatalogUrl :', client.stacCatalogUrl);
console.log('✓ JS smoke test passed');
