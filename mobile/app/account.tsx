import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Field, Hero, Screen, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function AccountScreen() {
  const { account, signOut, changePassword } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    setMessage('');
    try {
      await changePassword(next, current);
      setCurrent('');
      setNext('');
      setMessage('Password updated.');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to update password.');
    } finally {
      setSaving(false);
    }
  };

  return <Screen>
    <Hero eyebrow="Account" title={account?.name || 'Profile'} subtitle={account?.email} />
    <Card>
      <Text style={ui.title}>Account details</Text>
      <View style={styles.line}><Text style={ui.body}>Account type</Text><Text style={styles.value}>{account?.type === 'user' ? 'Driver' : account?.type}</Text></View>
      {account?.track_name ? <View style={styles.line}><Text style={ui.body}>Track</Text><Text style={styles.value}>{account.track_name}</Text></View> : null}
      {account?.role ? <View style={styles.line}><Text style={ui.body}>Permission</Text><Text style={styles.value}>{account.role.replace('_', ' ')}</Text></View> : null}
    </Card>
    <Card style={styles.form}>
      <View><Text style={ui.title}>Change password</Text><Text style={ui.body}>Use your current password to choose a new one.</Text></View>
      <Field secureTextEntry placeholder="Current password" value={current} onChangeText={setCurrent} />
      <Field secureTextEntry placeholder="New password (10+ characters)" value={next} onChangeText={setNext} />
      {message ? <Text style={message === 'Password updated.' ? styles.success : styles.error}>{message}</Text> : null}
      <Button title={saving ? 'Saving…' : 'Update password'} onPress={save} disabled={saving || !current || next.length < 10} />
    </Card>
    <Button tone="secondary" title="Sign out" onPress={signOut} />
  </Screen>;
}

const styles = StyleSheet.create({
  form: { gap: 13 },
  line: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 12, marginTop: 12 },
  value: { color: palette.ink, fontWeight: '800', textTransform: 'capitalize' },
  success: { color: palette.green, fontWeight: '700' },
  error: { color: palette.red, fontWeight: '700' },
});
