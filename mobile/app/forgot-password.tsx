import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Field } from '@/components/ui';
import { palette, shadow } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function ForgotPasswordScreen() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const submit = async () => {
    setError(''); setMessage(''); setSubmitting(true);
    try { setMessage(await requestPasswordReset(email)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'The reset request could not be completed.'); }
    finally { setSubmitting(false); }
  };

  return <SafeAreaView style={styles.screen}><KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.keyboard}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.center}>
    <View style={styles.brand}><View style={styles.mark}><Text style={styles.markText}>TO</Text></View><Text style={styles.brandName}>Track Ops</Text></View>
    <View style={styles.card}>
      <Pressable onPress={() => router.back()}><Text style={styles.back}>‹ Back to sign in</Text></Pressable>
      <Text style={styles.title}>Reset your password</Text>
      <Text style={styles.subtitle}>Enter the email for your driver, staff, vendor, or admin account. We’ll send a temporary password and require you to choose a new one after signing in.</Text>
      <Text style={styles.label}>Email address</Text>
      <Field autoFocus autoCapitalize="none" autoComplete="email" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" onSubmitEditing={submit} />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {message ? <Text style={styles.success}>{message}</Text> : null}
      <Button title={submitting ? 'Sending…' : message ? 'Send again' : 'Email temporary password'} onPress={submit} disabled={submitting || !email} />
    </View>
  </ScrollView></KeyboardAvoidingView></SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.navy }, keyboard: { flex: 1 }, center: { flexGrow: 1, justifyContent: 'center', padding: 22, width: '100%', maxWidth: 520, alignSelf: 'center' }, brand: { alignItems: 'center', marginBottom: 24 },
  mark: { width: 58, height: 58, borderRadius: 18, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center', marginBottom: 12 }, markText: { color: 'white', fontSize: 19, fontWeight: '900', letterSpacing: -1 }, brandName: { color: 'white', fontSize: 29, fontWeight: '900' },
  card: { backgroundColor: 'white', borderRadius: 24, padding: 22, gap: 14, ...shadow }, back: { color: palette.orange, fontSize: 13, fontWeight: '800' }, title: { color: palette.ink, fontSize: 24, fontWeight: '900' }, subtitle: { color: palette.muted, fontSize: 14, lineHeight: 21 }, label: { color: palette.ink, fontSize: 13, fontWeight: '800', marginTop: 4 },
  error: { color: palette.red, backgroundColor: palette.redSoft, padding: 11, borderRadius: 8, overflow: 'hidden' }, success: { color: palette.green, backgroundColor: palette.greenSoft, padding: 12, borderRadius: 8, lineHeight: 20, overflow: 'hidden' },
});
