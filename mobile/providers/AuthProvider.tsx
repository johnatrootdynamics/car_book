import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Platform } from 'react-native';

import type { Account } from '@/lib/types';

const API_URL = (process.env.EXPO_PUBLIC_API_URL || 'https://carbook.root-dynamics.com').replace(/\/$/, '');
const REFRESH_KEY = 'trackops.refresh-token';
const SOCIAL_REDIRECT_URI = 'trackops://auth/callback';

WebBrowser.maybeCompleteAuthSession();

type SocialProviders = { apple: boolean; google: boolean };
type AppleIdentity = { identityToken: string; authorizationCode?: string | null; givenName?: string | null; familyName?: string | null };

type AuthContextValue = {
  account: Account | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<Account>;
  signInWithApple: (identity: AppleIdentity) => Promise<Account>;
  signInWithGoogle: () => Promise<Account>;
  socialProviders: () => Promise<SocialProviders>;
  requestPasswordReset: (email: string) => Promise<string>;
  signOut: () => Promise<void>;
  changePassword: (newPassword: string, currentPassword?: string) => Promise<void>;
  deleteAccount: () => Promise<string>;
  openPortal: (target: string) => Promise<void>;
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

let webRefreshToken: string | null = null;
async function readRefreshToken() {
  return Platform.OS === 'web' ? webRefreshToken : SecureStore.getItemAsync(REFRESH_KEY);
}
async function saveRefreshToken(value: string | null) {
  if (Platform.OS === 'web') {
    webRefreshToken = value;
  } else if (value) {
    await SecureStore.setItemAsync(REFRESH_KEY, value);
  } else {
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  }
}

async function parseResponse(response: Response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.message || 'Something went wrong.') as Error & { code?: string };
    error.code = body.error;
    throw error;
  }
  return body;
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [account, setAccount] = useState<Account | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const refreshToken = await readRefreshToken();
    if (!refreshToken) return null;
    const response = await fetch(`${API_URL}/api/v1/mobile/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    const body = await parseResponse(response);
    setAccessToken(body.access_token);
    setAccount(body.account);
    return body.access_token as string;
  }, []);

  useEffect(() => {
    refresh().catch(() => saveRefreshToken(null)).finally(() => setLoading(false));
  }, [refresh]);

  const acceptSession = useCallback(async (body: any) => {
    await saveRefreshToken(body.refresh_token);
    setAccessToken(body.access_token);
    setAccount(body.account);
    return body.account as Account;
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await fetch(`${API_URL}/api/v1/mobile/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, device_name: `${Platform.OS} app` }),
    });
    const body = await parseResponse(response);
    return acceptSession(body);
  }, [acceptSession]);

  const socialProviders = useCallback(async () => {
    const response = await fetch(`${API_URL}/api/v1/mobile/auth/social/providers`);
    return parseResponse(response) as Promise<SocialProviders>;
  }, []);

  const signInWithApple = useCallback(async (identity: AppleIdentity) => {
    const response = await fetch(`${API_URL}/api/v1/mobile/auth/social/apple`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        identity_token: identity.identityToken,
        authorization_code: identity.authorizationCode,
        given_name: identity.givenName,
        family_name: identity.familyName,
        device_name: `${Platform.OS} app`,
      }),
    });
    return acceptSession(await parseResponse(response));
  }, [acceptSession]);

  const signInWithGoogle = useCallback(async () => {
    const startResponse = await fetch(`${API_URL}/api/v1/mobile/auth/social/google/start?app_redirect=${encodeURIComponent(SOCIAL_REDIRECT_URI)}`);
    const start = await parseResponse(startResponse);
    const result = await WebBrowser.openAuthSessionAsync(start.url, SOCIAL_REDIRECT_URI);
    if (result.type !== 'success' || !result.url) throw new Error('Google sign-in was canceled.');
    const callback = new URL(result.url);
    const callbackError = callback.searchParams.get('error');
    if (callbackError) throw new Error(callbackError);
    const code = callback.searchParams.get('code');
    if (!code) throw new Error('Google did not return a sign-in code.');
    const exchangeResponse = await fetch(`${API_URL}/api/v1/mobile/auth/social/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, device_name: `${Platform.OS} app` }),
    });
    return acceptSession(await parseResponse(exchangeResponse));
  }, [acceptSession]);

  const requestPasswordReset = useCallback(async (email: string) => {
    const response = await fetch(`${API_URL}/api/v1/mobile/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const body = await parseResponse(response);
    return body.message as string;
  }, []);

  const signOut = useCallback(async () => {
    const refreshToken = await readRefreshToken();
    if (refreshToken) {
      fetch(`${API_URL}/api/v1/mobile/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => undefined);
    }
    await saveRefreshToken(null);
    setAccessToken(null);
    setAccount(null);
  }, []);

  const api = useCallback(async <T,>(path: string, init: RequestInit = {}) => {
    let token = accessToken || (await refresh());
    const send = () => fetch(`${API_URL}/api/v1/mobile${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...init.headers,
        Authorization: `Bearer ${token}`,
      },
    });
    let response = await send();
    if (response.status === 401) {
      token = await refresh();
      if (token) response = await send();
    }
    return parseResponse(response) as Promise<T>;
  }, [accessToken, refresh]);

  const changePassword = useCallback(async (newPassword: string, currentPassword = '') => {
    const body = await api<any>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword, current_password: currentPassword, device_name: `${Platform.OS} app` }),
    });
    await saveRefreshToken(body.refresh_token);
    setAccessToken(body.access_token);
    setAccount(body.account);
  }, [api]);

  const deleteAccount = useCallback(async () => {
    const body = await api<{ message: string }>('/account', {
      method: 'DELETE',
      body: JSON.stringify({ confirmation: 'DELETE' }),
    });
    await saveRefreshToken(null);
    setAccessToken(null);
    setAccount(null);
    return body.message;
  }, [api]);

  const openPortal = useCallback(async (target: string) => {
    const body = await api<{ url: string }>('/auth/web-link', {
      method: 'POST',
      body: JSON.stringify({ target }),
    });
    await WebBrowser.openBrowserAsync(body.url, {
      presentationStyle: WebBrowser.WebBrowserPresentationStyle.FORM_SHEET,
      controlsColor: '#F97316',
    });
  }, [api]);

  const value = useMemo(() => ({ account, loading, signIn, signInWithApple, signInWithGoogle, socialProviders, requestPasswordReset, signOut, changePassword, deleteAccount, openPortal, api }), [account, loading, signIn, signInWithApple, signInWithGoogle, socialProviders, requestPasswordReset, signOut, changePassword, deleteAccount, openPortal, api]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
