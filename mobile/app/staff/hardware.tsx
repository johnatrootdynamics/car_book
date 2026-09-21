import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Scanner = { id: number; name: string; role: 'unassigned' | 'track_entrance' | 'track_exit'; status: string; reader_connected: boolean; last_seen_at?: string | null; software_version?: string | null };
type Camera = { id: number; name: string; status: string; camera_connected: boolean; last_seen_at?: string | null; software_version?: string | null };
type Observation = { id: number; scanner: string; role: string; result: string; reason?: string | null; epc: string; driver?: string | null; car?: { label: string } | null; observed_at: string };
type Hardware = { scanners: Scanner[]; cameras: Camera[]; observations: Observation[] };

const roles: Scanner['role'][] = ['track_entrance', 'track_exit', 'unassigned'];

export default function StaffHardwareScreen() {
  const { account, api } = useAuth();
  const [data, setData] = useState<Hardware | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError('');
    try { setData(await api<Hardware>('/staff/hardware')); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to load scanner status.'); }
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const setRole = async (scanner: Scanner, role: Scanner['role']) => {
    if (scanner.role === role) return;
    setBusy(scanner.id); setError('');
    try {
      await api(`/staff/hardware/scanners/${scanner.id}`, { method: 'PUT', body: JSON.stringify({ role }) });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to update the scanner zone.');
    } finally { setBusy(null); }
  };

  if (!data && !error) return <Loading />;
  return <Screen>
    <Hero eyebrow="Track hardware" title="Scanners & cameras" subtitle="A clear view of every zone, device connection, and recent read." />
    <Button tone="secondary" title="Refresh device status" onPress={load} />
    {error ? <Text style={styles.error}>{error}</Text> : null}

    <SectionTitle title="RFID scanners" />
    {data?.scanners.length ? data.scanners.map(scanner => <Card key={scanner.id}>
      <View style={ui.between}><View style={styles.deviceTitle}><View style={[styles.dot, scanner.reader_connected ? styles.online : styles.offline]} /><View><Text style={ui.title}>{scanner.name}</Text><Text style={ui.body}>{scanner.reader_connected ? 'Reader connected' : 'Reader offline'}{scanner.software_version ? ` · v${scanner.software_version}` : ''}</Text></View></View><Text style={styles.lastSeen}>{lastSeen(scanner.last_seen_at)}</Text></View>
      <Text style={styles.label}>Zone</Text>
      <View style={styles.roles}>{roles.map(role => <Pressable key={role} disabled={busy === scanner.id || account?.role !== 'office_staff'} onPress={() => setRole(scanner, role)} style={[styles.role, scanner.role === role && styles.roleActive]}><Text style={[styles.roleText, scanner.role === role && styles.roleTextActive]}>{roleLabel(role)}</Text></Pressable>)}</View>
    </Card>) : <Empty title="No RFID scanners" detail="Pair a scanner to this track and it will appear here." />}

    <SectionTitle title="Track cameras" />
    {data?.cameras.length ? data.cameras.map(camera => <Card key={camera.id} style={styles.camera}><View style={[styles.dot, camera.camera_connected ? styles.online : styles.offline]} /><View style={styles.cameraCopy}><Text style={ui.title}>{camera.name}</Text><Text style={ui.body}>{camera.camera_connected ? 'Camera connected' : 'Camera offline'}{camera.software_version ? ` · v${camera.software_version}` : ''}</Text></View><Text style={styles.lastSeen}>{lastSeen(camera.last_seen_at)}</Text></Card>) : <Empty title="No track cameras" detail="Paired cameras will appear here with their live connection status." />}

    <SectionTitle title="Recent reads" />
    {data?.observations.length ? data.observations.map(item => <Card key={item.id} style={styles.read}><View style={ui.between}><Text style={styles.readTitle}>{item.driver || item.car?.label || 'Unknown tag'}</Text><Text style={[styles.result, item.result === 'allowed' ? styles.resultGood : styles.resultBad]}>{item.result}</Text></View><Text style={ui.body}>{item.scanner} · {roleLabel(item.role as Scanner['role'])}</Text>{item.car && item.driver ? <Text style={styles.meta}>{item.car.label}</Text> : null}<Text style={styles.meta}>{item.reason || item.epc} · {new Date(item.observed_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</Text></Card>) : <Empty title="No recent reads" detail="Scanner activity will appear here as vehicles enter and exit." />}
  </Screen>;
}

function roleLabel(role: Scanner['role']) {
  if (role === 'track_entrance') return 'Entrance';
  if (role === 'track_exit') return 'Exit';
  return 'Unassigned';
}

function lastSeen(value?: string | null) {
  if (!value) return 'Never seen';
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  return minutes < 2 ? 'Just now' : minutes < 60 ? `${minutes}m ago` : `${Math.round(minutes / 60)}h ago`;
}

const styles = StyleSheet.create({
  error: { color: palette.red, fontWeight: '800' },
  deviceTitle: { flexDirection: 'row', alignItems: 'center', gap: 10, flex: 1 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  online: { backgroundColor: palette.green },
  offline: { backgroundColor: '#98A2B3' },
  lastSeen: { color: palette.muted, fontSize: 11 },
  label: { color: palette.ink, fontSize: 12, fontWeight: '800', marginTop: 15, marginBottom: 8 },
  roles: { flexDirection: 'row', gap: 7 },
  role: { flex: 1, minHeight: 38, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: palette.line, borderRadius: 11, backgroundColor: 'white' },
  roleActive: { backgroundColor: palette.navy, borderColor: palette.navy },
  roleText: { color: palette.muted, fontSize: 11, fontWeight: '800' },
  roleTextActive: { color: 'white' },
  camera: { flexDirection: 'row', alignItems: 'center', gap: 11 },
  cameraCopy: { flex: 1 },
  read: { gap: 4 },
  readTitle: { color: palette.ink, fontSize: 16, fontWeight: '900', flex: 1 },
  result: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4, overflow: 'hidden', fontSize: 10, fontWeight: '900', textTransform: 'uppercase' },
  resultGood: { color: palette.green, backgroundColor: palette.greenSoft },
  resultBad: { color: palette.red, backgroundColor: palette.redSoft },
  meta: { color: palette.muted, fontSize: 12, lineHeight: 17 },
});
