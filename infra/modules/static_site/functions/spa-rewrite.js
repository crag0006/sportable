// SPA routing for CloudFront, done at the edge instead of with custom error
// responses.
//
// WHY NOT custom_error_response
//   CloudFront's custom error responses are DISTRIBUTION-WIDE. Mapping 404 to
//   /index.html with status 200 therefore rewrites the API's genuine 404s too,
//   and the frontend receives HTML where it expected JSON. There is no
//   per-behaviour override for error responses.
//
//   A CloudFront Function can be attached to ONE behaviour, so the SPA gets its
//   fallback and /api/* is left completely alone.
//
// WHAT IT DOES
//   Rewrites any path that does not look like a file to /index.html, so the
//   SPA's own router can handle it. Requests for real assets — anything with a
//   file extension — pass through untouched and are served from S3.
//
// COST
//   CloudFront Functions run at the edge in under a millisecond. The first
//   2 million invocations each month are free.

function handler(event) {
  var request = event.request;
  var uri = request.uri;

  // Already a file: /assets/app.4f2b1c.js, /favicon.ico, /index.html
  if (uri.includes('.')) {
    return request;
  }

  // A directory-style path: serve the app and let client-side routing take over.
  request.uri = '/index.html';
  return request;
}
