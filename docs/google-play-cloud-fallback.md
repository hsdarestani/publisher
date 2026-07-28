# Google Play cloud fallback

A+ Publisher normally calls the official Google Play Android Publisher API from the production server.

If Google Edge returns an HTML `403` before the request reaches the API, Publisher automatically dispatches the same operation to the repository workflow `google-play-cloud-operation.yml`. The workflow:

1. Uses the encrypted `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` GitHub Actions secret.
2. Fetches a short-lived, signed operation payload from Publisher.
3. Applies localized listings, images and the generated Data Safety CSV through the official Google API.
4. Calls Publisher back with a sanitized result.
5. Updates the original Compliance Run, so users remain on the same job page.

The callback token is scoped to one compliance run and expires after one hour. Service-account private keys and OAuth access tokens are never included in the payload or callback.
