import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Car, TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type Detail = {
  driver: { id: number; name: string; email: string; phone?: string; driver_class: string; attended_count: number; registered_count: number; note_count: number };
  class_options: string[];
  events: { registration_id: number; event: TrackEvent; car: Car; checked_in_at?: string | null; inspection_state: string }[];
  notes: { id: number; text: string; author: string; created_at: string }[];
  class_changes: { id: number; previous: string; new: string; author: string; created_at: string }[];
};

export default function StaffDriverDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useAuth();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    try {
      const body = await api<Detail>(`/staff/people/drivers/${id}`);
      setDetail(body);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to load this driver.');
    }
  }, [api, id]);

  useEffect(() => { load(); }, [load]);

  const updateClass = async (driverClass: string) => {
    if (!detail || driverClass === detail.driver.driver_class) return;
    setBusy(true); setMessage('');
    try {
      await api(`/staff/people/drivers/${id}/class`, { method: 'PUT', body: JSON.stringify({ driver_class: driverClass }) });
      await load();
      setMessage(`Driver class changed to ${driverClass}.`);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to update the driver class.');
    } finally { setBusy(false); }
  };

  const addNote = async () => {
    if (!note.trim()) return;
    setBusy(true); setMessage('');
    try {
      await api(`/staff/people/drivers/${id}/notes`, { method: 'POST', body: JSON.stringify({ text: note }) });
      setNote('');
      await load();
      setMessage('Track note added.');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to add the note.');
    } finally { setBusy(false); }
  };

  if (!detail) return message ? <Screen><Empty title="Driver unavailable" detail={message} /></Screen> : <Loading />;
  const driver = detail.driver;
  return <Screen>
    <Hero eyebrow={`Class ${driver.driver_class}`} title={driver.name} subtitle={`${driver.email}${driver.phone ? ` · ${driver.phone}` : ''}`} />
    <View style={styles.stats}>
      <Card style={styles.stat}><Text style={styles.statValue}>{driver.attended_count}</Text><Text style={styles.statLabel}>Attended</Text></Card>
      <Card style={styles.stat}><Text style={styles.statValue}>{driver.registered_count}</Text><Text style={styles.statLabel}>Registered</Text></Card>
      <Card style={styles.stat}><Text style={styles.statValue}>{driver.note_count}</Text><Text style={styles.statLabel}>Notes</Text></Card>
    </View>
    {message ? <Text style={styles.message}>{message}</Text> : null}

    <SectionTitle title="Driver class" />
    <View style={styles.chips}>{detail.class_options.map(option => <Pressable disabled={busy} key={option} onPress={() => updateClass(option)} style={[styles.chip, option === driver.driver_class && styles.chipActive]}><Text style={[styles.chipText, option === driver.driver_class && styles.chipTextActive]}>{option}</Text></Pressable>)}</View>

    <SectionTitle title="Track notes" />
    <Card style={styles.noteComposer}><Field multiline value={note} onChangeText={setNote} placeholder="Add a note for track staff" style={styles.noteField} /><Button title={busy ? 'Saving…' : 'Add note'} disabled={busy || !note.trim()} onPress={addNote} /></Card>
    {detail.notes.length ? detail.notes.map(item => <Card key={item.id}><Text style={styles.noteText}>{item.text}</Text><Text style={styles.meta}>{item.author} · {shortDate(item.created_at)}</Text></Card>) : <Empty title="No track notes" detail="Add operational notes that staff should know about this driver." />}

    <SectionTitle title="Event history" />
    {detail.events.length ? detail.events.map(item => <Card key={item.registration_id}><View style={ui.between}><View style={styles.eventCopy}><Text style={ui.title}>{item.event.name}</Text><Text style={ui.body}>{eventDate(item.event.date)} · {item.car.label}</Text></View><Text style={[styles.status, item.checked_in_at && styles.statusGood]}>{item.checked_in_at ? 'Attended' : 'Registered'}</Text></View><Text style={styles.meta}>Inspection: {item.inspection_state.replace('_', ' ')}</Text></Card>) : <Empty title="No event history" detail="This driver has no registrations at your track." />}

    {detail.class_changes.length ? <><SectionTitle title="Class history" />{detail.class_changes.map(change => <Card key={change.id} style={styles.change}><Text style={ui.title}>{change.previous} → {change.new}</Text><Text style={styles.meta}>{change.author} · {shortDate(change.created_at)}</Text></Card>)}</> : null}
  </Screen>;
}

function shortDate(value: string) {
  return new Date(value).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', gap: 8 },
  stat: { flex: 1, alignItems: 'center', paddingHorizontal: 4 },
  statValue: { color: palette.ink, fontSize: 23, fontWeight: '900' },
  statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { minWidth: 48, minHeight: 42, paddingHorizontal: 14, borderRadius: 13, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', alignItems: 'center', justifyContent: 'center' },
  chipActive: { backgroundColor: palette.navy, borderColor: palette.navy },
  chipText: { color: palette.ink, fontWeight: '900' },
  chipTextActive: { color: 'white' },
  noteComposer: { gap: 12 },
  noteField: { minHeight: 92, paddingTop: 14, textAlignVertical: 'top' },
  noteText: { color: palette.ink, fontSize: 15, lineHeight: 22 },
  meta: { color: palette.muted, fontSize: 12, lineHeight: 18, marginTop: 7 },
  message: { color: palette.green, fontWeight: '800' },
  eventCopy: { flex: 1, paddingRight: 8 },
  status: { color: palette.muted, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  statusGood: { color: palette.green },
  change: { paddingVertical: 13 },
});
