import { Redirect, router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Field } from '@/components/ui';
import { palette, shadow } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function LoginScreen() {
  const { account, loading, signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  if (!loading && account) return <Redirect href={account.must_change_password ? '/change-password' : '/(tabs)'} />;

  const submit = async () => {
    setError(''); setSubmitting(true);
    try {
      const nextAccount = await signIn(email, password);
      router.replace(nextAccount.must_change_password ? '/change-password' : '/(tabs)');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to sign in.');
    } finally { setSubmitting(false); }
  };

  return <SafeAreaView style={styles.screen}><KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.center}>
    <View style={styles.brand}><View style={styles.mark}><Text style={styles.markText}>TO</Text></View><Text style={styles.brandName}>Track Ops</Text><Text style={styles.tagline}>Your track day, in your pocket.</Text></View>
    <View style={styles.card}>
      <Text style={styles.title}>Welcome back</Text><Text style={styles.subtitle}>One login for drivers, staff, vendors, and admins.</Text>
      <Text style={styles.label}>Email address</Text><Field autoCapitalize="none" autoComplete="email" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" />
      <Text style={styles.label}>Password</Text><Field autoCapitalize="none" autoComplete="current-password" secureTextEntry value={password} onChangeText={setPassword} placeholder="Your password" onSubmitEditing={submit} />
      {error ? <Text style={styles.error}>{error}</Text> : null}<Button title={submitting ? 'Signing in…' : 'Sign in'} onPress={submit} disabled={submitting || !email || !password} />
    </View>
  </KeyboardAvoidingView></SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.navy }, center: { flex: 1, justifyContent: 'center', padding: 22 }, brand: { alignItems: 'center', marginBottom: 28 },
  mark: { width: 58, height: 58, borderRadius: 18, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center', marginBottom: 12 }, markText: { color: 'white', fontSize: 19, fontWeight: '900', letterSpacing: -1 },
  brandName: { color: 'white', fontSize: 29, fontWeight: '900' }, tagline: { color: '#D0D5DD', marginTop: 5 }, card: { backgroundColor: 'white', borderRadius: 24, padding: 22, gap: 12, ...shadow },
  title: { color: palette.ink, fontSize: 24, fontWeight: '900' }, subtitle: { color: palette.muted, lineHeight: 20, marginBottom: 8 }, label: { color: palette.ink, fontSize: 13, fontWeight: '800', marginTop: 4 }, error: { color: palette.red, backgroundColor: palette.redSoft, padding: 11, borderRadius: 10, overflow: 'hidden' },
});
