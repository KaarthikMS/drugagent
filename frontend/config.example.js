// Copy to config.js, or generate it with scripts/write-frontend-config.sh.
// config.js is gitignored because its values are per-deployment, not
// because they are secret.
window.APP_CONFIG = {
  clientId: '<UserPoolClientId>',
  hostedUi: 'https://<prefix>.auth.ap-south-1.amazoncognito.com',
  apiEndpoint: 'https://<api-id>.execute-api.ap-south-1.amazonaws.com',
};
