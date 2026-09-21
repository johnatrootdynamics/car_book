import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
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
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<number | null>(null);
  const [pairing, setPairing] = useState(false);
  const [scannerName, setScannerName] = useState('');
  const [pairingCode, setPairingCode] = useState('');

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

  const pairScanner = async () => {
    setPairing(true); setError(''); setNotice('');
    try {
      const result = await api<{ message: string }>('/staff/hardware/scanners/register', {
        method: 'POST',
        body: JSON.stringify({ name: scannerName, pairing_code: pairingCode }),
      });
      setScannerName(''); setPairingCode(''); setNotice(result.message); await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to pair the scanner.');
    } finally { setPairing(false); }
  };

  if (!data && !error) return <Loading />;
  return <Screen>
    <Hero eyebrow="Track hardware" title="Scanners & cameras" subtitle="A clear view of every zone, device connection, and recent read." />
    <Button tone="secondary" title="Refresh device status" onPress={load} />
    {notice ? <Text style={styles.notice}>{notice}</Text> : null}
    {error ? <Text style={styles.error}>{error}</Text> : null}

    {account?.role === 'office_staff' ? <>
      <SectionTitle title="Pair a scanner" />
      <Card style={styles.pairCard}>
        <Text style={ui.body}>Enter the temporary code shown on the scanner setup screen.</Text>
        <View><Text style={ui.label}>Scanner name</Text><Field placeholder="North gate scanner" value={scannerName} onChangeText={setScannerName} /></View>
        <View><Text style={ui.label}>Pairing code</Text><Field autoCapitalize="characters" autoCorrect={false} placeholder="ABC123" value={pairingCode} onChangeText={setPairingCode} /></View>
        <Button title={pairing ? 'Pairing…' : 'Pair scanner'} disabled={pairing || !scannerName.trim() || !pairingCode.trim()} onPress={pairScanner} />
      </Card>
    </> : null}

    <SectionTitle title="RFID scanners" />
    {data?.scanners.length ? data.scanners.map(scanner => <Card key={scanner.id}>
      <View style={ui.between}><View style={styles.deviceTitle}><View style={[styles.dot, isOnline(scanner.reader_connected, scanner.last_seen_at) ? styles.online : styles.offline]} /><View><Text style={ui.title}>{scanner.name}</Text><Text style={ui.body}>{isOnline(scanner.reader_connected, scanner.last_seen_at) ? 'Reader connected' : 'Reader offline'}{scanner.software_version ? ` · v${scanner.software_version}` : ''}</Text></View></View><Text style={styles.lastSeen}>{lastSeen(scanner.last_seen_at)}</Text></View>
      <Text style={styles.label}>Zone</Text>
      <View style={styles.roles}>{roles.map(role => <Pressable key={role} disabled={busy === scanner.id || account?.role !== 'office_staff'} onPress={() => setRole(scanner, role)} style={[styles.role, scanner.role === role && styles.roleActive]}><Text style={[styles.roleText, scanner.role === role && styles.roleTextActive]}>{roleLabel(role)}</Text></Pressable>)}</View>
    </Card>) : <Empty title="No RFID scanners" detail="Pair a scanner to this track and it will appear here." />}

    <SectionTitle title="Track cameras" />
    {data?.cameras.length ? data.cameras.map(camera => <Card key={camera.id} style={styles.camera}><View style={[styles.dot, isOnline(camera.camera_connected, camera.last_seen_at) ? styles.online : styles.offline]} /><View style={styles.cameraCopy}><Text style={ui.title}>{camera.name}</Text><Text style={ui.body}>{isOnline(camera.camera_connected, camera.last_seen_at) ? 'Camera connected' : 'Camera offline'}{camera.software_version ? ` · v${camera.software_version}` : ''}</Text></View><Text style={styles.lastSeen}>{lastSeen(camera.last_seen_at)}</Text></Card>) : <Empty title="No track cameras" detail="Paired cameras will appear here with their live connection status." />}

    <SectionTitle title="Recent reads" />
    {data?.observations.length ? data.observations.map(item => <Card key={item.id} style={styles.read}><View style={ui.between}><Text style={styles.readTitle}>{item.driver || item.car?.label || 'Unknown tag'}</Text><Text style={[styles.result, ['allowed', 'accepted'].includes(item.result.toLowerCase()) ? styles.resultGood : styles.resultBad]}>{item.result}</Text></View><Text style={ui.body}>{item.scanner} · {roleLabel(item.role as Scanner['role'])}</Text>{item.car && item.driver ? <Text style={styles.meta}>{item.car.label}</Text> : null}<Text style={styles.meta}>{item.reason || item.epc} · {new Date(item.observed_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</Text></Card>) : <Empty title="No recent reads" detail="Scanner activity will appear here as vehicles enter and exit." />}
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

function isOnline(connected: boolean, value?: string | null) {
  return Boolean(connected && value && Date.now() - new Date(value).getTime() < 5 * 60 * 1000);
}

const styles = StyleSheet.create({
  error: { color: palette.red, fontWeight: '800' },
  notice: { color: palette.green, fontWeight: '800' },
  pairCard: { gap: 13 },
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
