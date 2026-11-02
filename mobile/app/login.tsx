import * as AppleAuthentication from 'expo-apple-authentication';
import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Field } from '@/components/ui';
import { BrandLogo } from '@/components/BrandLogo';
import { palette, shadow } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function LoginScreen() {
  const { account, loading, signIn, signInWithApple, signInWithGoogle, socialProviders } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [providers, setProviders] = useState({ apple: Platform.OS === 'ios', google: false });
  const website = (process.env.EXPO_PUBLIC_API_URL || 'https://carbook.root-dynamics.com').replace(/\/$/, '');
  useEffect(() => { socialProviders().then(setProviders).catch(() => undefined); }, [socialProviders]);
  if (!loading && account) return <Redirect href={account.must_change_password ? '/change-password' : '/(tabs)'} />;

  const finishSignIn = (nextAccount: typeof account) => {
    if (nextAccount) router.replace(nextAccount.must_change_password ? '/change-password' : '/(tabs)');
  };

  const submit = async () => {
    setError(''); setSubmitting(true);
    try {
      const nextAccount = await signIn(email, password);
      finishSignIn(nextAccount);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to sign in.');
    } finally { setSubmitting(false); }
  };

  const submitApple = async () => {
    setError(''); setSubmitting(true);
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.FULL_NAME, AppleAuthentication.AppleAuthenticationScope.EMAIL],
      });
      if (!credential.identityToken) throw new Error('Apple did not return an identity token.');
      finishSignIn(await signInWithApple({ identityToken: credential.identityToken, authorizationCode: credential.authorizationCode, givenName: credential.fullName?.givenName, familyName: credential.fullName?.familyName }));
    } catch (caught: any) {
      if (caught?.code !== 'ERR_REQUEST_CANCELED') setError(caught instanceof Error ? caught.message : 'Apple sign-in failed.');
    } finally { setSubmitting(false); }
  };

  const submitGoogle = async () => {
    setError(''); setSubmitting(true);
    try { finishSignIn(await signInWithGoogle()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Google sign-in failed.'); }
    finally { setSubmitting(false); }
  };

  return <SafeAreaView style={styles.screen}><KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.keyboard}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.center}>
    <View style={styles.brand}><BrandLogo width={310} /><Text style={styles.tagline}>Your track day, in your pocket.</Text></View>
    <View style={styles.card}>
      <Text style={styles.title}>Welcome back</Text><Text style={styles.subtitle}>One login for drivers, staff, vendors, and admins.</Text>
      <Text style={styles.label}>Email address</Text><Field autoCapitalize="none" autoComplete="email" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" />
      <View style={styles.passwordLabel}><Text style={styles.label}>Password</Text><Pressable onPress={() => router.push('/forgot-password')}><Text style={styles.link}>Forgot password?</Text></Pressable></View><Field autoCapitalize="none" autoComplete="current-password" secureTextEntry value={password} onChangeText={setPassword} placeholder="Your password" onSubmitEditing={submit} />
      {error ? <Text style={styles.error}>{error}</Text> : null}<Button title={submitting ? 'Signing in…' : 'Sign in'} onPress={submit} disabled={submitting || !email || !password} />
      {providers.apple || providers.google ? <><View style={styles.divider}><View style={styles.dividerLine} /><Text style={styles.dividerText}>or continue with</Text><View style={styles.dividerLine} /></View>
        {providers.apple && Platform.OS === 'ios' ? <AppleAuthentication.AppleAuthenticationButton buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE} buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE} cornerRadius={6} style={styles.socialButton} onPress={submitApple} /> : null}
        {providers.google ? <Pressable disabled={submitting} onPress={submitGoogle} style={({ pressed }) => [styles.googleButton, (pressed || submitting) && styles.pressed]}><Text style={styles.googleMark}>G</Text><Text style={styles.googleText}>Continue with Google</Text></Pressable> : null}
      </> : null}
    </View>
    <View style={styles.legalLinks}><Pressable onPress={() => Linking.openURL(`${website}/privacy`)}><Text style={styles.legalLink}>Privacy</Text></Pressable><Pressable onPress={() => Linking.openURL(`${website}/terms`)}><Text style={styles.legalLink}>Terms</Text></Pressable><Pressable onPress={() => Linking.openURL(`${website}/support`)}><Text style={styles.legalLink}>Support</Text></Pressable></View>
  </ScrollView></KeyboardAvoidingView></SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.canvas }, keyboard: { flex: 1 }, center: { flexGrow: 1, justifyContent: 'center', padding: 22, width: '100%', maxWidth: 520, alignSelf: 'center' }, brand: { alignItems: 'center', marginBottom: 22 },
  tagline: { color: palette.muted, marginTop: 15 }, card: { backgroundColor: palette.surface, borderRadius: 8, borderWidth: 1, borderColor: palette.line, borderTopWidth: 3, borderTopColor: palette.primary, padding: 22, gap: 12, ...shadow },
  title: { color: palette.ink, fontSize: 24, fontWeight: '900' }, subtitle: { color: palette.muted, lineHeight: 20, marginBottom: 8 }, label: { color: palette.ink, fontSize: 13, fontWeight: '800', marginTop: 4 }, passwordLabel: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, link: { color: palette.accent, fontSize: 13, fontWeight: '800' }, error: { color: palette.red, backgroundColor: palette.redSoft, padding: 11, borderRadius: 10, overflow: 'hidden' },
  divider: { flexDirection: 'row', alignItems: 'center', gap: 10, marginVertical: 2 }, dividerLine: { flex: 1, height: 1, backgroundColor: palette.line }, dividerText: { color: palette.muted, fontSize: 12, fontWeight: '700' }, socialButton: { width: '100%', height: 50 }, googleButton: { minHeight: 50, borderRadius: 6, backgroundColor: 'white', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12 }, googleMark: { color: '#4285F4', fontSize: 18, fontWeight: '900' }, googleText: { color: '#111827', fontSize: 15, fontWeight: '800' }, pressed: { opacity: .7 },
  legalLinks: { flexDirection: 'row', justifyContent: 'center', gap: 20, marginTop: 18 }, legalLink: { color: palette.muted, fontSize: 12, fontWeight: '700' },
});
