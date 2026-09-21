import { Redirect, router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Field } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function ChangePasswordScreen() {
  const { account, changePassword } = useAuth(); const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState(''); const [error, setError] = useState(''); const [saving, setSaving] = useState(false);
  if (!account) return <Redirect href="/login" />;
  const save = async () => { if (password !== confirm) return setError('The passwords do not match.'); setSaving(true); setError(''); try { await changePassword(password); router.replace('/(tabs)'); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to change your password.'); } finally { setSaving(false); } };
  return <SafeAreaView style={styles.screen}><KeyboardAvoidingView style={styles.wrap} behavior={Platform.OS === 'ios' ? 'padding' : undefined}><View style={styles.icon}><Text style={styles.iconText}>✓</Text></View><Text style={styles.title}>Make this account yours</Text><Text style={styles.subtitle}>Replace the temporary password before using Track Ops. Use at least 10 characters.</Text><Field secureTextEntry placeholder="New password" value={password} onChangeText={setPassword} /><Field secureTextEntry placeholder="Confirm new password" value={confirm} onChangeText={setConfirm} />{error ? <Text style={styles.error}>{error}</Text> : null}<Button title={saving ? 'Saving…' : 'Continue'} onPress={save} disabled={saving || password.length < 10 || !confirm} /></KeyboardAvoidingView></SafeAreaView>;
}
const styles = StyleSheet.create({ screen: { flex: 1, backgroundColor: palette.canvas }, wrap: { flex: 1, justifyContent: 'center', padding: 24, gap: 14 }, icon: { width: 58, height: 58, borderRadius: 18, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center', marginBottom: 8 }, iconText: { color: 'white', fontWeight: '900', fontSize: 26 }, title: { color: palette.ink, fontSize: 29, fontWeight: '900' }, subtitle: { color: palette.muted, fontSize: 15, lineHeight: 22, marginBottom: 10 }, error: { color: palette.red, backgroundColor: palette.redSoft, padding: 11, borderRadius: 10 } });
