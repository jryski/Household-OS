// Operator-pinned review host configuration. Deploy-time only; nothing in the
// URL, a record or a model message can change it. Example mode is the default.
//
// Connected mode needs every field below, all supplied by the operator after a
// separately approved activation (see review/README.md). Shape, with invented
// placeholder values:
//
// {
//   mode: 'connected', enabled: true,
//   origin: 'https://<project-ref>.supabase.co',
//   publishableKey: 'sb_publishable_<value>',
//   oauthClientId: '<dedicated public OAuth client UUID>',
//   redirectUri: 'https://<review host>/<exact callback path>',
//   binding: {human_grant_id, auth_subject, upstream_client_id, board_id}
// }
//
// upstream_client_id must equal oauthClientId. Setting enabled: false keeps the
// host disconnected without removing the pinned values.
export default Object.freeze({mode:'example'});
