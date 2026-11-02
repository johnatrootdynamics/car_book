import { useState } from 'react';
import { router, Stack } from 'expo-router';
import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Field, Hero, Screen, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

export default function AccountScreen() {
  const { account, signOut, changePassword, deleteAccount } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const website = (process.env.EXPO_PUBLIC_API_URL || 'https://carbook.root-dynamics.com').replace(/\/$/, '');

  const goBack = () => router.replace('/(tabs)/more');

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

  const handleSignOut = async () => {
    setSigningOut(true);
    setMessage('');
    try {
      await signOut();
      router.replace('/login');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to sign out.');
      setSigningOut(false);
    }
  };

  const confirmDeletion = () => Alert.alert(
    'Permanently delete account?',
    'Your profile, active sessions, connections, posts, comments, and uploaded Community content will be removed. Required purchase, waiver, inspection, and safety records may be retained without your profile information. This cannot be undone.',
    [
      { text: 'Keep account', style: 'cancel' },
      {
        text: 'Delete account',
        style: 'destructive',
        onPress: async () => {
          setDeleting(true);
          setMessage('');
          try {
            await deleteAccount();
            router.replace('/login');
          } catch (caught) {
            setMessage(caught instanceof Error ? caught.message : 'Unable to delete the account.');
            setDeleting(false);
          }
        },
      },
    ],
  );

  return <Screen>
    <Stack.Screen options={{
      headerLeft: () => <Pressable
        accessibilityRole="button"
        accessibilityLabel="Back"
        hitSlop={10}
        onPress={goBack}
        style={({ pressed }) => [styles.headerBack, pressed && styles.headerBackPressed]}
      >
        <Text style={styles.headerBackArrow}>‹</Text>
        <Text style={styles.headerBackText}>Back</Text>
      </Pressable>,
    }} />
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
    <Card style={styles.form}>
      <View><Text style={ui.title}>Privacy, terms & support</Text><Text style={ui.body}>Review how Track Ops handles your information or get help.</Text></View>
      {[
        ['Privacy Policy', '/privacy'],
        ['Terms of Use', '/terms'],
        ['Community Guidelines', '/community-guidelines'],
        ['Support', '/support'],
      ].map(([label, path]) => <Pressable key={path} accessibilityRole="link" onPress={() => Linking.openURL(`${website}${path}`)} style={styles.linkRow}><Text style={styles.linkText}>{label}</Text><Text style={styles.linkArrow}>›</Text></Pressable>)}
    </Card>
    <Button tone="secondary" title={signingOut ? 'Signing out…' : 'Sign out'} onPress={handleSignOut} disabled={signingOut} />
    <Card style={styles.dangerCard}>
      <View><Text style={styles.dangerTitle}>Delete account</Text><Text style={ui.body}>Permanently remove your account and Community data from Track Ops.</Text></View>
      <Button tone="danger" title={deleting ? 'Deleting account…' : 'Delete account'} onPress={confirmDeletion} disabled={deleting} />
    </Card>
  </Screen>;
}

const styles = StyleSheet.create({
  headerBack: { minHeight: 38, flexDirection: 'row', alignItems: 'center', gap: 4, paddingRight: 12 },
  headerBackPressed: { opacity: 0.55 },
  headerBackArrow: { color: palette.accent, fontSize: 31, lineHeight: 33, fontWeight: '500' },
  headerBackText: { color: palette.accent, fontSize: 16, fontWeight: '800' },
  form: { gap: 13 },
  line: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 12, marginTop: 12 },
  value: { color: palette.ink, fontWeight: '800', textTransform: 'capitalize' },
  success: { color: palette.green, fontWeight: '700' },
  error: { color: palette.red, fontWeight: '700' },
  linkRow: { minHeight: 47, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: palette.line },
  linkText: { color: palette.ink, fontWeight: '800', fontSize: 14 },
  linkArrow: { color: palette.accent, fontSize: 25 },
  dangerCard: { gap: 14, borderColor: palette.red },
  dangerTitle: { color: palette.red, fontSize: 18, fontWeight: '900' },
});
