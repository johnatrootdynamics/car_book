const configuredApiUrl = process.env.EXPO_PUBLIC_API_URL?.trim();

/**
 * Canonical TrackOps web and API origin.
 *
 * Keep the environment override for local/staging builds. Production falls
 * back to the TLS-enabled canonical hostname so native clients never depend
 * on the retired CarBook domain.
 */
export const API_URL = (configuredApiUrl || 'https://www.trackops.tech').replace(/\/$/, '');

export const WEBSITE_URL = API_URL;
