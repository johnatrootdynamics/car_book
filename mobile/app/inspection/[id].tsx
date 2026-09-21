import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Field, Loading, Screen, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Inspection = {
  registration_id: number;
  driver: string;
  car: { label: string };
  event: { name: string; date: string };
  checked_in: boolean;
  rules: { id: number; text: string; checked: boolean }[];
  notes: string;
  status: 'not_started' | 'needs_attention' | 'passed';
};

export default function InspectionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useAuth();
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ inspection: Inspection }>(`/staff/inspections/${id}`).then(body => {
      setInspection(body.inspection);
      setChecked(new Set(body.inspection.rules.filter(rule => rule.checked).map(rule => rule.id)));
      setNotes(body.inspection.notes || '');
    }).catch(caught => setError(caught instanceof Error ? caught.message : 'Unable to load inspection.'));
  }, [api, id]);

  const toggle = (ruleId: number) => setChecked(current => {
    const next = new Set(current);
    if (next.has(ruleId)) next.delete(ruleId); else next.add(ruleId);
    return next;
  });

  const save = async () => {
    setSaving(true); setError('');
    try {
      const body = await api<{ inspection: Inspection }>(`/staff/inspections/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ checked_rule_ids: [...checked], notes }),
      });
      setInspection(body.inspection);
      setChecked(new Set(body.inspection.rules.filter(rule => rule.checked).map(rule => rule.id)));
      setNotes(body.inspection.notes || '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to save inspection.');
    } finally {
      setSaving(false);
    }
  };

  if (!inspection && !error) return <Loading />;
  if (!inspection) return <Screen><View style={styles.notice}><Text style={styles.error}>{error}</Text></View></Screen>;
  const passed = inspection.status === 'passed';
  return <Screen>
    <View style={styles.heading}><Text style={styles.eyebrow}>VEHICLE INSPECTION</Text><Text style={styles.title}>{inspection.driver}</Text><Text style={ui.body}>{inspection.car.label} · {inspection.event.name} · {eventDate(inspection.event.date)}</Text></View>
    <View style={[styles.status, passed ? styles.pass : styles.pending]}><Text style={[styles.statusText, passed ? styles.passText : styles.pendingText]}>{passed ? '✓ INSPECTION PASSED' : inspection.status === 'needs_attention' ? 'NEEDS ATTENTION' : 'NOT STARTED'}</Text></View>
    <Card style={styles.checklist}>
      <Text style={ui.title}>Track checklist</Text>
      {!inspection.rules.length ? <Text style={ui.body}>No active inspection rules are configured for this track.</Text> : inspection.rules.map((rule, index) => <Pressable key={rule.id} onPress={() => toggle(rule.id)} style={[styles.rule, index > 0 && styles.divider]}>
        <View style={[styles.checkbox, checked.has(rule.id) && styles.checked]}><Text style={styles.checkmark}>{checked.has(rule.id) ? '✓' : ''}</Text></View>
        <Text style={styles.ruleText}>{rule.text}</Text>
      </Pressable>)}
    </Card>
    <Card style={styles.notes}><Text style={ui.label}>Inspection notes</Text><Field multiline numberOfLines={4} maxLength={500} style={styles.notesField} placeholder="Optional notes for track staff" value={notes} onChangeText={setNotes} /></Card>
    {error ? <Text style={styles.error}>{error}</Text> : null}
    <Button title={saving ? 'Saving inspection…' : checked.size === inspection.rules.length && inspection.rules.length ? 'Pass & save inspection' : 'Save inspection'} onPress={save} disabled={saving || !inspection.rules.length} />
  </Screen>;
}

const styles = StyleSheet.create({
  heading: { gap: 5, paddingVertical: 4 },
  eyebrow: { color: palette.orange, fontWeight: '900', letterSpacing: 1.2, fontSize: 11 },
  title: { color: palette.ink, fontSize: 29, fontWeight: '900' },
  status: { borderRadius: 13, padding: 13, alignItems: 'center' },
  pass: { backgroundColor: palette.greenSoft },
  pending: { backgroundColor: palette.orangeSoft },
  statusText: { fontWeight: '900', fontSize: 13, letterSpacing: 0.5 },
  passText: { color: palette.green },
  pendingText: { color: '#C2410C' },
  checklist: { paddingVertical: 4 },
  rule: { minHeight: 64, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  divider: { borderTopWidth: 1, borderTopColor: palette.line },
  checkbox: { width: 29, height: 29, borderRadius: 9, borderWidth: 2, borderColor: '#D0D5DD', alignItems: 'center', justifyContent: 'center' },
  checked: { backgroundColor: palette.green, borderColor: palette.green },
  checkmark: { color: 'white', fontWeight: '900', fontSize: 17 },
  ruleText: { flex: 1, color: palette.ink, fontSize: 15, fontWeight: '700', lineHeight: 21 },
  notes: { gap: 6 },
  notesField: { height: 112, paddingTop: 14, textAlignVertical: 'top' },
  notice: { marginTop: 30, borderRadius: 14, padding: 16, backgroundColor: palette.redSoft },
  error: { color: palette.red, fontWeight: '800', lineHeight: 20 },
});
