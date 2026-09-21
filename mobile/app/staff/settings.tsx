import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Payment = { provider: string; label: string; enabled: boolean; mode: 'live' | 'test'; live_configured: boolean; test_configured: boolean };
type Staff = { id: number; name: string; email: string; role: 'track_staff' | 'office_staff'; must_change_password: boolean; can_reset: boolean };
type Settings = {
  track: { id: number; name: string; city: string; state: string };
  payments: Payment[];
  staff: Staff[];
  inspection_rules: { id: number; text: string; active: boolean }[];
  waivers: { id: number; title: string; active: boolean; required_for_checkin: boolean }[];
  email_templates: { key: string; label: string; configured: boolean; enabled: boolean; ticket_design: string }[];
  driver_classes: { id: number; name: string }[];
};

type Credentials = Record<string, string>;

export default function StaffSettingsScreen() {
  const { api } = useAuth();
  const [data, setData] = useState<Settings | null>(null);
  const [track, setTrack] = useState({ name: '', city: '', state: '' });
  const [rule, setRule] = useState('');
  const [staffForm, setStaffForm] = useState({ name: '', email: '', role: 'track_staff' as Staff['role'] });
  const [selectedProvider, setSelectedProvider] = useState('');
  const [credentials, setCredentials] = useState<Credentials>({});
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  const apply = (settings: Settings) => {
    setData(settings);
    setTrack({ name: settings.track.name, city: settings.track.city, state: settings.track.state });
  };

  const load = useCallback(async () => {
    try {
      const body = await api<{ settings: Settings }>('/staff/settings');
      apply(body.settings);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to load track settings.');
    }
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const run = async (key: string, action: () => Promise<{ settings?: Settings; message?: string }>) => {
    setBusy(key); setMessage('');
    try {
      const result = await action();
      if (result.settings) apply(result.settings);
      setMessage(result.message || 'Settings saved.');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to save this setting.');
    } finally { setBusy(''); }
  };

  const saveTrack = () => run('track', () => api('/staff/settings/track', { method: 'PUT', body: JSON.stringify(track) }));
  const updatePayment = (payment: Payment, changes: Record<string, unknown>) => run(`payment-${payment.provider}`, () => api(`/staff/settings/payments/${payment.provider}`, { method: 'PUT', body: JSON.stringify(changes) }));
  const saveCredentials = (payment: Payment) => {
    const values = Object.fromEntries(Object.entries(credentials).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
    if (!Object.keys(values).length) { setMessage('Enter at least one credential to update.'); return; }
    run(`credentials-${payment.provider}`, async () => {
      const result = await api<{ settings: Settings }>(`/staff/settings/payments/${payment.provider}`, { method: 'PUT', body: JSON.stringify(values) });
      setCredentials({}); setSelectedProvider(''); return result;
    });
  };
  const addRule = () => run('rule', async () => {
    const result = await api<{ settings: Settings }>('/staff/settings/inspection-rules', { method: 'POST', body: JSON.stringify({ text: rule }) });
    setRule(''); return result;
  });
  const toggleRule = (id: number, active: boolean) => run(`rule-${id}`, () => api(`/staff/settings/inspection-rules/${id}`, { method: 'PUT', body: JSON.stringify({ active }) }));
  const addStaff = () => Alert.alert('Create staff account?', `TrackOps will create ${staffForm.email} and email a temporary password.`, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Create & email', onPress: () => run('staff', async () => {
      const result = await api<{ settings: Settings }>('/staff/settings/staff', { method: 'POST', body: JSON.stringify(staffForm) });
      setStaffForm({ name: '', email: '', role: 'track_staff' }); return result;
    }) },
  ]);
  const resetStaff = (member: Staff) => Alert.alert('Reset password?', `A random temporary password will be emailed to ${member.email}.`, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Reset & email', style: 'destructive', onPress: () => run(`reset-${member.id}`, () => api(`/staff/settings/staff/${member.id}/reset-password`, { method: 'POST' })) },
  ]);
  const changeStaffRole = (member: Staff, role: Staff['role']) => {
    if (member.role === role) return;
    run(`role-${member.id}`, () => api(`/staff/settings/staff/${member.id}/role`, { method: 'PUT', body: JSON.stringify({ role }) }));
  };

  if (!data) return message ? <Screen><Empty title="Settings unavailable" detail={message} /></Screen> : <Loading />;
  return <Screen>
    <Hero eyebrow="Office management" title="Track settings" subtitle="Manage the essentials without leaving the app." />
    {message ? <View style={styles.notice}><Text style={styles.noticeText}>{message}</Text></View> : null}

    <SectionTitle title="Track profile" />
    <Card style={styles.form}><Field value={track.name} onChangeText={name => setTrack(current => ({ ...current, name }))} placeholder="Track name" /><View style={styles.twoFields}><Field style={{ flex: 1 }} value={track.city} onChangeText={city => setTrack(current => ({ ...current, city }))} placeholder="City" /><Field style={{ flex: 1 }} value={track.state} onChangeText={state => setTrack(current => ({ ...current, state }))} placeholder="State" /></View><Button title={busy === 'track' ? 'Saving…' : 'Save track profile'} disabled={!!busy || !track.name || !track.city || !track.state} onPress={saveTrack} /></Card>

    <SectionTitle title="Payment providers" />
    {data.payments.map(payment => <Card key={payment.provider} style={styles.provider}>
      <View style={ui.between}><View><Text style={ui.title}>{payment.label}</Text><Text style={ui.body}>{payment.enabled ? 'Enabled' : 'Disabled'} · {payment.mode === 'test' ? 'Test mode' : 'Live mode'}</Text></View><View style={[styles.dot, payment.enabled ? styles.enabled : styles.disabled]} /></View>
      <View style={styles.paymentMeta}><Text style={styles.meta}>Live credentials {payment.live_configured ? 'ready' : 'missing'}</Text><Text style={styles.meta}>Test credentials {payment.test_configured ? 'ready' : 'missing'}</Text></View>
      <View style={styles.actions}><Pressable disabled={!!busy} onPress={() => updatePayment(payment, { enabled: !payment.enabled })} style={styles.smallButton}><Text style={styles.smallButtonText}>{payment.enabled ? 'Disable' : 'Enable'}</Text></Pressable><Pressable disabled={!!busy} onPress={() => updatePayment(payment, { mode: payment.mode === 'live' ? 'test' : 'live' })} style={styles.smallButton}><Text style={styles.smallButtonText}>Use {payment.mode === 'live' ? 'test' : 'live'}</Text></Pressable><Pressable onPress={() => { setSelectedProvider(selectedProvider === payment.provider ? '' : payment.provider); setCredentials({}); }} style={styles.smallButton}><Text style={styles.smallButtonText}>Credentials</Text></Pressable></View>
      {selectedProvider === payment.provider ? <View style={styles.credentials}><Text style={styles.help}>Only fields you enter are changed. Existing secrets are never shown.</Text>{credentialFields.map(field => <Field key={field.key} secureTextEntry={field.secret} autoCapitalize="none" placeholder={field.label} value={credentials[field.key] || ''} onChangeText={value => setCredentials(current => ({ ...current, [field.key]: value }))} />)}<Button title={busy === `credentials-${payment.provider}` ? 'Saving…' : 'Save credentials'} disabled={!!busy} onPress={() => saveCredentials(payment)} /></View> : null}
    </Card>)}

    <SectionTitle title="Staff accounts" />
    <Card style={styles.form}><Field value={staffForm.name} onChangeText={name => setStaffForm(current => ({ ...current, name }))} placeholder="Full name" /><Field value={staffForm.email} onChangeText={email => setStaffForm(current => ({ ...current, email }))} placeholder="Email address" autoCapitalize="none" keyboardType="email-address" /><View style={styles.roles}>{(['track_staff', 'office_staff'] as const).map(role => <Pressable key={role} onPress={() => setStaffForm(current => ({ ...current, role }))} style={[styles.role, staffForm.role === role && styles.roleActive]}><Text style={[styles.roleText, staffForm.role === role && styles.roleTextActive]}>{role === 'track_staff' ? 'Track staff' : 'Office staff'}</Text></Pressable>)}</View><Button title={busy === 'staff' ? 'Creating…' : 'Create account & email password'} disabled={!!busy || !staffForm.name || !staffForm.email.includes('@')} onPress={addStaff} /></Card>
    {data.staff.map(member => <Card key={member.id} style={styles.staffCard}><View style={styles.staffRow}><View style={styles.staffCopy}><Text style={ui.title}>{member.name}</Text><Text style={ui.body}>{member.email}</Text><Text style={styles.meta}>{member.must_change_password ? 'Password change pending' : 'Password active'}</Text></View>{member.can_reset ? <Pressable disabled={!!busy} onPress={() => resetStaff(member)} style={styles.smallButton}><Text style={styles.smallButtonText}>Reset</Text></Pressable> : null}</View><View style={styles.roles}>{(['track_staff', 'office_staff'] as const).map(role => <Pressable key={role} disabled={!!busy} onPress={() => changeStaffRole(member, role)} style={[styles.role, member.role === role && styles.roleActive]}><Text style={[styles.roleText, member.role === role && styles.roleTextActive]}>{role === 'track_staff' ? 'Track staff' : 'Office staff'}</Text></Pressable>)}</View></Card>)}

    <SectionTitle title="Inspection checklist" />
    <View style={styles.addRow}><Field style={{ flex: 1 }} value={rule} onChangeText={setRule} placeholder="New inspection rule" /><View style={{ width: 82 }}><Button title="Add" disabled={!!busy || !rule.trim()} onPress={addRule} /></View></View>
    {data.inspection_rules.length ? <Card style={styles.list}>{data.inspection_rules.map((item, index) => <Pressable key={item.id} disabled={!!busy} onPress={() => toggleRule(item.id, !item.active)} style={[styles.ruleRow, index > 0 && styles.divider]}><View style={[styles.check, item.active && styles.checkActive]}><Text style={styles.checkText}>{item.active ? '✓' : ''}</Text></View><Text style={[styles.ruleText, !item.active && styles.inactive]}>{item.text}</Text><Text style={styles.meta}>{item.active ? 'Active' : 'Off'}</Text></Pressable>)}</Card> : <Empty title="No inspection rules" detail="Add the first item in your vehicle checklist." />}

    <SectionTitle title="Email & ticket design" />
    {data.email_templates.map(template => <Card key={template.key} style={styles.summaryRow}><View style={styles.staffCopy}><Text style={ui.title}>{template.label}</Text><Text style={ui.body}>{template.configured ? 'Customized' : 'Using default'} · {template.ticket_design.replace('_', ' ')}</Text></View><Text style={[styles.state, template.enabled ? styles.stateGood : styles.stateMuted]}>{template.enabled ? 'ON' : 'OFF'}</Text></Card>)}

    <SectionTitle title="Waivers" />
    {data.waivers.length ? data.waivers.map(waiver => <Card key={waiver.id} style={styles.summaryRow}><View style={styles.staffCopy}><Text style={ui.title}>{waiver.title}</Text><Text style={ui.body}>{waiver.required_for_checkin ? 'Required at check-in' : 'Optional'}</Text></View><Text style={[styles.state, waiver.active ? styles.stateGood : styles.stateMuted]}>{waiver.active ? 'ACTIVE' : 'OFF'}</Text></Card>) : <Empty title="No waiver templates" detail="Waiver templates can be connected when your BoldSign setup is ready." />}

    <SectionTitle title="Driver classes" />
    <Card><View style={styles.classList}>{data.driver_classes.map(item => <View key={item.id} style={styles.classChip}><Text style={styles.classText}>{item.name}</Text></View>)}</View></Card>
  </Screen>;
}

const credentialFields = [
  { key: 'public_key', label: 'Live public/client ID', secret: false },
  { key: 'secret_key', label: 'Live secret key', secret: true },
  { key: 'webhook_secret', label: 'Live webhook secret/ID', secret: true },
  { key: 'merchant_id', label: 'Live merchant ID', secret: false },
  { key: 'test_public_key', label: 'Test public/client ID', secret: false },
  { key: 'test_secret_key', label: 'Test secret key', secret: true },
  { key: 'test_webhook_secret', label: 'Test webhook secret/ID', secret: true },
  { key: 'test_merchant_id', label: 'Test merchant ID', secret: false },
];

const styles = StyleSheet.create({
  notice: { backgroundColor: palette.greenSoft, borderRadius: 13, padding: 13 },
  noticeText: { color: palette.green, fontWeight: '800' },
  form: { gap: 11 },
  twoFields: { flexDirection: 'row', gap: 9 },
  provider: { gap: 12 },
  dot: { width: 12, height: 12, borderRadius: 6 },
  enabled: { backgroundColor: palette.green },
  disabled: { backgroundColor: '#98A2B3' },
  paymentMeta: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  meta: { color: palette.muted, fontSize: 11, lineHeight: 16, fontWeight: '700' },
  actions: { flexDirection: 'row', gap: 7 },
  smallButton: { minHeight: 38, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', borderRadius: 11, paddingHorizontal: 11, alignItems: 'center', justifyContent: 'center' },
  smallButtonText: { color: palette.ink, fontSize: 11, fontWeight: '900' },
  credentials: { gap: 9, paddingTop: 3 },
  help: { color: palette.muted, fontSize: 12, lineHeight: 18 },
  roles: { flexDirection: 'row', gap: 8 },
  role: { flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: palette.line, borderRadius: 12 },
  roleActive: { backgroundColor: palette.navy, borderColor: palette.navy },
  roleText: { color: palette.muted, fontWeight: '800' },
  roleTextActive: { color: 'white' },
  staffCard: { gap: 12 },
  staffRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  staffCopy: { flex: 1, gap: 2 },
  addRow: { flexDirection: 'row', gap: 9, alignItems: 'center' },
  list: { paddingVertical: 2 },
  ruleRow: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  divider: { borderTopWidth: 1, borderTopColor: palette.line },
  check: { width: 28, height: 28, borderRadius: 9, borderWidth: 1, borderColor: palette.line, alignItems: 'center', justifyContent: 'center' },
  checkActive: { backgroundColor: palette.green, borderColor: palette.green },
  checkText: { color: 'white', fontWeight: '900' },
  ruleText: { color: palette.ink, fontSize: 14, fontWeight: '800', flex: 1 },
  inactive: { color: palette.muted, textDecorationLine: 'line-through' },
  summaryRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  state: { fontSize: 10, fontWeight: '900' },
  stateGood: { color: palette.green },
  stateMuted: { color: palette.muted },
  classList: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  classChip: { minWidth: 46, borderRadius: 12, backgroundColor: palette.orangeSoft, paddingHorizontal: 13, paddingVertical: 9, alignItems: 'center' },
  classText: { color: '#C2410C', fontWeight: '900' },
});
